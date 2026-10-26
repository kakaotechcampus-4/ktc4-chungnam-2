"""추천 막힘 조언 평가셋(#588) — cases_advice.json의 run 상태를 agent가 보는 모양(조언 입력, 도구 결과, 검증 재료)으로 바꾼다.
DB를 쓰지 않는다.

- 도구는 운영 코드 `agent.tools.RunToolContext`가 그대로 돈다. 데이터만 recommend.api 대신 FixtureRecommendApi(케이스의
  깔때기, 근거 줄, 시뮬레이션)에서 읽는다 — patched_recommend_api()가 agent.tools의 recommend_api를 잠시 바꾼다. 그래서 도구
  결과의 모양(core.funnel_view, simulate_view, advice_evidence), 인자 검사(배율, 근거 줄 id), 상위 N개 자르기, 기록이 운영과 같다.
- 조언 입력은 core.advice_input, 대상 판정은 core.run_advice_target, 검증은 core.verify_run_advice, 렌더는
  core.render_run_advice다(agent.flows.advise_run과 같은 재료). 평가가 보는 것은 프롬프트와 모델이다.
- simulate_filter는 필터를 다시 돌리지 않고 케이스에 적은 증가 수로 after를 만든다: 반경은 넓힌 도보 분 이하의 radius_gain 중
  가장 큰 값, 근거 줄은 끈 줄들의 gain 합. 그만큼 「반경 밖 제거」, 「실격 조건 제거」가 줄고 passed가 는다.
- 근거 글은 지어낸 예시다. 실제 사용자 글을 넣지 않는다.

평가 도구라 agent의 core와 tools(api.py가 아닌 모듈), recommend.core의 상수를 직접 가져온다. 운영 코드는 이 파일을 가져오지 않는다.
"""

import json
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Collection, Iterator, Mapping, Sequence

from agent import core, tools
from common.errors import AppError
from llm.schemas import RunAdviceOutput
from llm.tests.eval_agent.fixtures import CHIPS, MEMBER_NAMES, NOW
from recommend import api as recommend_api
from recommend.core import RANKING_STAGE, WIDEN_LIMIT_MIN, WIDEN_STEP_MIN, passed_count

CASES_PATH = Path(__file__).with_name("cases_advice.json")

# recommend.flows._run_pipeline의 깔때기 단계 순서. 케이스의 funnel은 이 라벨 → 탈락 수(적지 않으면 0)
STAGES = ("카테고리 후보 풀", "반경 밖 제거", "영업 종료 제거", "추천 가능 아님 제거", "실격 조건 제거", "이미 제안·거절됨",
          RANKING_STAGE)
RADIUS_STAGE, DISQUALIFY_STAGE, EXCLUDED_STAGE = "반경 밖 제거", "실격 조건 제거", "이미 제안·거절됨"

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
    """케이스 하나의 run 상태. raw는 recommend.api가 돌려줄 값과 같은 모양이다."""
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
    def same_runs(self) -> int:
        return core.same_category_runs(self.recent, self.meta["created_at"])

    @property
    def is_target(self) -> bool:
        return core.run_advice_target(self.meta["status"], self.meta["result_count"], self.same_runs)

    def line_id(self, local: str) -> str:
        return self.local_ids[local]

    # ---- 조언 한 번 (agent.flows.advise_run과 같은 재료)

    def tool_context(self) -> tools.RunToolContext:
        return tools.RunToolContext(
            run_id=self.run_id, requester_id=REQUESTER, meta=self.meta, session_factory=_NoSession,
            fact_labels=recommend_api.fact_labels(),
        )

    def advice_input(self, ctx: tools.RunToolContext) -> dict[str, Any]:
        """깔때기를 미리 읽어(t0) 넣은 조언 입력. patched_recommend_api() 안에서 부른다."""
        funnel = ctx.prefetch(core.PREFETCH_CALL_ID, "get_run_funnel")
        return core.advice_input(self.meta, self.same_runs, funnel)

    def member_names(self) -> list[str]:
        return list(MEMBER_NAMES[:self.case.get("members", 3)])

    def verify(self, out: RunAdviceOutput, ctx: tools.RunToolContext) -> core.VerifiedAdvice:
        """agent.flows._checked_advice와 같은 AdviceContext로 검증한다."""
        return core.verify_run_advice(out, core.AdviceContext(
            run_id=ctx.run_id, tool_results=ctx.results, tool_names=ctx.names,
            own_lines={line["line_id"]: line["author_id"] == REQUESTER for line in self.lines},
            evidence_texts=[line["text"] for line in self.lines if line["text"]], radius=core.run_radius(self.meta),
            member_names=self.member_names(),
        ))

    def render(self, draft: core.AdviceDraft) -> Any:
        """저장될 조언 행 → API의 RunAdvice(core.render_run_advice). 빈 조언이면 None(204)."""
        row = SimpleNamespace(kind=draft.kind, claims=draft.claims, advice=draft.advice, actions=draft.actions)
        return core.render_run_advice(self.run_id, row)

    # ---- simulate_filter

    def simulate(self, radius_factor: float | None, disabled: Collection[str]) -> dict[str, Any]:
        unknown = set(disabled) - set(self.gains)
        if unknown:
            raise AppError("NOT_FOUND")   # recommend.flows.simulate_filter: 그 run의 근거 줄이 아닌 id
        radius_gain = self._radius_gain(radius_factor)
        line_gain = sum(self.gains[i] for i in set(disabled))
        funnel = [dict(e) for e in self.funnel["funnel"]]
        for entry in funnel:
            if entry["label"] == RADIUS_STAGE:
                entry["removed_count"] = max(0, entry["removed_count"] - radius_gain)
            elif entry["label"] == DISQUALIFY_STAGE:
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


class _NoSession:
    """RunToolContext.read()가 여는 세션 자리. FixtureRecommendApi는 db를 보지 않는다."""

    def __enter__(self) -> "_NoSession":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def rollback(self) -> None:
        pass


class FixtureRecommendApi:
    """agent.tools가 부르는 recommend.api 네 함수를 케이스 데이터로 돌려준다(시그니처와 반환 모양이 같다)."""

    def __init__(self, worlds: Mapping[str, AdviceWorld]):
        self._worlds = dict(worlds)

    def _world(self, run_id: str) -> AdviceWorld:
        if run_id not in self._worlds:
            raise AppError("NOT_FOUND")
        return self._worlds[run_id]

    def get_recent_runs(self, db: Any, *, run_id: str, limit: int = 10) -> list[dict]:
        return [dict(r) for r in self._world(run_id).recent[:limit]]

    def get_run_funnel(self, db: Any, *, run_id: str) -> dict:
        return _copy(self._world(run_id).funnel)

    def get_run_evidence(self, db: Any, *, run_id: str) -> list[dict]:
        return [dict(line) for line in self._world(run_id).lines]

    def simulate_filter(
        self, db: Any, *, run_id: str, radius_factor: float | None = None, disable_line_ids: Collection[str] = (),
    ) -> dict:
        if radius_factor is not None and not radius_factor > 0:
            raise ValueError("radius_factor는 0보다 커야 한다")
        return self._world(run_id).simulate(radius_factor, disable_line_ids)


@contextmanager
def patched_recommend_api(worlds: Sequence[AdviceWorld]) -> Iterator[FixtureRecommendApi]:
    """agent.tools가 읽는 recommend.api를 이 블록 동안 FixtureRecommendApi로 바꾼다. run_id로 케이스를 가르므로 여러 케이스를
    한꺼번에 넣고 동시에 돌려도 된다."""
    fake = FixtureRecommendApi({w.run_id: w for w in worlds})
    saved = tools.recommend_api
    tools.recommend_api = fake
    try:
        yield fake
    finally:
        tools.recommend_api = saved


def _line(case_id: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    """케이스의 줄 → recommend.api.get_run_evidence의 한 줄. 칩 줄은 칩 표대로 글(label), 키, 방향을 채운다."""
    chip = raw.get("chip")
    if chip:
        label, fact_key, wants = CHIPS[chip]
        text, fact_key, wants = raw.get("text", label), raw.get("fact_key", fact_key), raw.get("wants", wants)
    else:
        text, fact_key, wants = raw["text"], raw.get("fact_key"), raw.get("wants")
    return {
        "line_id": _id(case_id, raw["id"]), "text": text, "badge": raw.get("badge", "required"), "fact_key": fact_key,
        "wants": wants, "is_active": raw.get("active", True), "author_id": AUTHORS[raw["by"]], "chip_id": chip,
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
