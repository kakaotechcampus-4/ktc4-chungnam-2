"""추천 막힘 조언 회귀 셋(#588 평가셋을 #750에서 옮김) — cases_advice.json의 run 상태를 recommend.api가 돌려주는 모양으로
바꾸고, flows.advise_run과 같은 순서로 core의 절차를 돌린다. DB를 쓰지 않는다.

- 깔때기, 근거 줄, 메타, 최근 run은 recommend.api.get_run_funnel, get_run_evidence, get_run_meta, get_recent_runs와 같은 모양이다.
- simulate_filter는 필터를 다시 돌리지 않고 케이스에 적은 증가 수로 after를 만든다: 반경은 넓힌 도보 분 이하의 radius_gain 중
  가장 큰 값, 근거 줄은 끈 줄들의 gain 합. 그만큼 「반경 밖 제거」, 「실격 조건 제거」가 줄고 passed가 는다.
- 칩 줄의 글, 키, 방향은 칩 표(pins.chips, 정본 docs/constraints.md)에서 읽는다 — 여기 다시 적지 않는다.
- 근거 글은 지어낸 예시다. 실제 사용자 글을 넣지 않는다.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Collection, Mapping

from agent import core
from common.errors import AppError
from pins import chips
from recommend import api as recommend_api
from recommend.core import RANKING_STAGE, WIDEN_LIMIT_MIN, WIDEN_STEP_MIN, passed_count

CASES_PATH = Path(__file__).with_name("cases_advice.json")
NOW = datetime(2026, 10, 15, 3, 0, tzinfo=timezone.utc)

# recommend.flows._run_pipeline의 깔때기 단계 순서. 케이스의 funnel은 이 라벨 → 탈락 수(적지 않으면 0)
STAGES = ("카테고리 후보 풀", core.RADIUS_STAGE, "영업 종료 제거", "추천 가능 아님 제거", core.DISQUALIFY_STAGE,
          core.EXCLUDED_STAGE, RANKING_STAGE)

REQUESTER = "u1"
AUTHORS = {"self": REQUESTER, "other": "u2", "other2": "u3"}
_NS = uuid.UUID("5b8f0a3e-588a-4d1c-9e5e-000000000588")


def load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _id(case_id: str, local: str) -> str:
    """run과 근거 줄 id — 운영처럼 UUID 문자열이고 같은 케이스면 늘 같다."""
    return str(uuid.uuid5(_NS, f"{case_id}:{local}"))


@dataclass
class AdviceWorld:
    """케이스 하나의 run 상태. 칸은 recommend.api가 돌려줄 값과 같은 모양이다."""
    case: dict[str, Any]
    run_id: str
    meta: dict[str, Any]                 # recommend.api.get_run_meta
    recent: list[dict[str, Any]]         # recommend.api.get_recent_runs
    funnel: dict[str, Any]               # recommend.api.get_run_funnel
    lines: list[dict[str, Any]]          # recommend.api.get_run_evidence
    local_ids: dict[str, str]            # 케이스의 줄 이름(l1 …) → line_id
    gains: dict[str, int]                # line_id → 그 줄을 끄면 더 남는 곳
    radius_gain: dict[int, int]          # 넓힌 도보 분 → 더 남는 곳

    @property
    def is_target(self) -> bool:
        same_runs = core.same_category_runs(self.recent, self.meta["created_at"])
        return core.run_advice_target(self.meta["status"], self.meta["result_count"], same_runs)

    def line_id(self, local: str) -> str:
        return self.local_ids[local]

    def own(self, line_id: str) -> bool:
        return next(line["author_id"] for line in self.lines if line["line_id"] == line_id) == REQUESTER

    # ---- 조언 한 번 (flows.advise_run과 같은 순서: 깔때기, 근거 줄 → 필요한 시뮬레이션 → 고르기)

    def advise(self) -> tuple[core.AdviceDraft, dict[str, dict[str, Any]]]:
        """(조언, 돌린 시뮬레이션의 인자)."""
        funnel = core.funnel_view(self.funnel)
        lines = core.advice_evidence(self.lines, REQUESTER, recommend_api.fact_labels())
        next_factor = core.next_radius_factor(self.meta)
        wanted = core.advice_simulations(funnel, lines, next_factor)
        sims = {cid: core.simulate_view(self.simulate(**args), **args) for cid, args in wanted.items()}
        return core.choose_run_advice(self.run_id, funnel, lines, sims, next_factor), wanted

    def render(self, draft: core.AdviceDraft) -> Any:
        """저장될 조언 행 → API의 RunAdvice(core.render_run_advice). 빈 조언이면 None(204)."""
        row = SimpleNamespace(kind=draft.kind, claims=draft.claims, advice=draft.advice, actions=draft.actions)
        return core.render_run_advice(self.run_id, row)

    # ---- simulate_filter (recommend.api.simulate_filter의 {before, after})

    def simulate(self, radius_factor: float | None, disable_line_ids: Collection[str]) -> dict[str, Any]:
        unknown = set(disable_line_ids) - set(self.gains)
        if unknown:
            raise AppError("NOT_FOUND")   # recommend.flows.simulate_filter: 그 run의 근거 줄이 아닌 id
        radius_gain = self._radius_gain(radius_factor)
        line_gain = sum(self.gains[i] for i in set(disable_line_ids))
        funnel = [dict(e) for e in self.funnel["funnel"]]
        for entry in funnel:
            if entry["label"] == core.RADIUS_STAGE:
                entry["removed_count"] = max(0, entry["removed_count"] - radius_gain)
            elif entry["label"] == core.DISQUALIFY_STAGE:
                entry["removed_count"] = max(0, entry["removed_count"] - line_gain)
        passed = self.funnel["passed_count"] + radius_gain + line_gain
        result = min(3, passed)
        funnel[-1]["removed_count"] = passed - result   # 상위 3곳 선정
        after = {"result_count": result, "funnel": funnel, "passed_count": passed_count(result, funnel)}
        return {"before": _copy(self.funnel), "after": after}

    def _radius_gain(self, radius_factor: float | None) -> int:
        if radius_factor is None:
            return 0
        walk = self.meta["default_radius_walk_min"] * radius_factor
        reached = [gain for minutes, gain in self.radius_gain.items() if minutes <= walk + 1e-6]
        return max(reached, default=0)


def _copy(outcome: Mapping[str, Any]) -> dict[str, Any]:
    return {**outcome, "funnel": [dict(e) for e in outcome["funnel"]]}


def _line(case_id: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    """케이스의 줄 → recommend.api.get_run_evidence의 한 줄. 칩 줄은 칩 표대로 글(label), 키, 방향을 채운다."""
    chip = chips.chip_for(raw["chip"]) if raw.get("chip") else None
    if chip is not None:
        text, fact_key, wants = raw.get("text", chip.label), raw.get("fact_key", chip.fact_key), raw.get("wants", chip.wants)
    else:
        text, fact_key, wants = raw["text"], raw.get("fact_key"), raw.get("wants")
    return {
        "line_id": _id(case_id, raw["id"]), "text": text, "badge": raw.get("badge", "required"), "fact_key": fact_key,
        "wants": wants, "is_active": raw.get("active", True), "author_id": AUTHORS[raw["by"]], "chip_id": raw.get("chip"),
        "enforced": fact_key is not None, "not_enforced_reason": None if fact_key is not None else "no_key",   # recommend의 값(#740)
    }


def build(case: Mapping[str, Any]) -> AdviceWorld:
    cid = case["id"]
    run_id = _id(cid, "run")
    stages = dict(case["funnel"])
    funnel_entries = [{"label": label, "removed_count": stages.get(label, 0)} for label in STAGES]
    result_count = case["result_count"]
    funnel = {"result_count": result_count, "funnel": funnel_entries,
              "passed_count": passed_count(result_count, funnel_entries)}
    created = NOW - timedelta(minutes=5)
    meta = {
        "run_id": run_id, "map_id": "map_eval", "category": case["category"], "requested_by": REQUESTER,
        "status": case.get("status", "done"), "result_count": result_count, "created_at": created,
        "default_radius_walk_min": case["walk_min"], "widen_limit_walk_min": WIDEN_LIMIT_MIN,
        "widen_step_walk_min": WIDEN_STEP_MIN,
    }
    # 같은 요청자, 같은 카테고리의 run(최근순). 이 run이 맨 앞이고 앞선 run은 하루씩 이르다
    recent = [{"run_id": run_id, "status": meta["status"], "result_count": result_count, "created_at": created}]
    recent += [{"run_id": _id(cid, f"run{i}"), "status": "done", "result_count": 1, "created_at": created - timedelta(days=i)}
               for i in range(1, case["same_category_runs"])]
    lines = [_line(cid, raw) for raw in case.get("lines", [])]
    local_ids = {raw["id"]: _id(cid, raw["id"]) for raw in case.get("lines", [])}
    gains = {local_ids[raw["id"]]: raw.get("gain", 0) for raw in case.get("lines", [])}
    radius_gain = {int(minutes): gain for minutes, gain in case.get("radius_gain", {}).items()}
    return AdviceWorld(case=dict(case), run_id=run_id, meta=meta, recent=recent, funnel=funnel, lines=lines,
                       local_ids=local_ids, gains=gains, radius_gain=radius_gain)
