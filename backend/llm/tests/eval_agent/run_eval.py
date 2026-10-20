"""agent 평가 — 평가셋을 실제 모델(gpt-6-luna, 엘리스 ML API)로 N번씩 돌려 표를 낸다. 진단(#534, cases.json)과 추천 막힘
조언(#588, cases_advice.json).

    cd backend
    python -m llm.tests.eval_agent.run_eval                 # 진단: target이 있는 케이스 × 5회
    python -m llm.tests.eval_agent.run_eval --runs 1 --cases e08_split_diff_axes_vs_stall
    python -m llm.tests.eval_agent.run_eval --target advice # 조언: 모든 케이스 × 5회

- 키는 backend/.env의 ELICE_ML_API_BASE_URL, ELICE_ML_API_KEY(settings)로만 읽는다. 키와 URL을 출력하거나 파일에 쓰지 않는다.
- 진단: target이 있는 케이스. reasoning_effort=none 고정이다(도구 호출 제약, #532). 우선순위는 #582부터 모델이 아니라 코드
  규칙이라 여기서 돌지 않는다 — 기대값은 test_eval_cases.py가 core.fallback_order로 본다.
- 결과는 results/(커밋하지 않는다, .gitignore)에 JSON(호출마다 원본)과 Markdown(요약표)으로 남긴다. 사유 글은 평가셋의
  지어낸 예시뿐이다.
- 모델 출력 검증은 운영과 같은 agent.core.verify_diagnosis다. "검증 통과"는 decision=suggest였던 호출 중 초안이 남은 비율이다.
- 조언: 도구는 운영 코드 agent.tools.RunToolContext가 돌고 데이터만 케이스에서 읽는다(fixtures_advice). 검증은 운영과 같은
  agent.core.verify_run_advice다. 지표는 진단과 같고, 종류 일치와 남의 줄 버튼(모델 원문, 검증 뒤)을 더 본다.
"""

import argparse
import json
import statistics
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from agent import core
from common.settings import settings
from llm import client as llm_client
from llm import service
from llm.prompts import AGENT_ADVISE_RUN_PROMPT_VERSION, AGENT_DIAGNOSE_PROMPT_VERSION, DIAGNOSIS_TOOLS
from llm.schemas import AgentCallFailed
from llm.tests.eval_agent import fixtures as fx
from llm.tests.eval_agent import fixtures_advice as fxa

RESULTS_DIR = Path(__file__).with_name("results")
# 엘리스 Serverless gpt-6-luna 요금(1M 토큰당, 기획안 13절): 입력 ₩152, 캐시된 입력 ₩15, 출력 ₩761
PRICE_IN, PRICE_CACHED, PRICE_OUT = 152, 15, 761
FORBIDDEN_RAW = ("확정", "결정하세요", "여기로 가")
# 조언 원문에서 따로 세는 말: 조건을 빼거나 반경을 넓히라는 명령형(프롬프트 출력 규칙 4), 추천이 거르지 않는 글(알러지, 가격)
RELAX_RAW = ("빼세요", "끄세요", "넓히세요", "빼라", "끄라", "넓혀라")
NOT_FILTERED_RAW = (*core.SAFETY_WORDS, "가격", "비싸", "비용", "입장료")

_local = threading.local()


class RecordingClient:
    """요청마다 걸린 시간과 사용량(캐시 입력, 추론 토큰 포함)을 스레드별로 남기는 클라이언트 감싸개. 본문은 남기지 않는다."""

    def __init__(self, inner: Any):
        self._inner = inner
        self.chat = SimpleNamespace(completions=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs: Any) -> Any:
        started = time.monotonic()
        row: dict[str, Any] = {"reasoning_effort": kwargs.get("reasoning_effort", "default")}
        try:
            completion = self._inner.chat.completions.parse(**kwargs)
        except Exception as exc:
            row |= {"ms": _ms(started), "error": type(exc).__name__}
            if type(exc).__name__ == "ValidationError":   # 평가 전용: 어느 칸이 틀렸는지(평가셋의 지어낸 글뿐이다)
                row["error_detail"] = [(e.get("loc"), e.get("type")) for e in exc.errors()][:5]
            _local.requests.append(row)
            raise
        usage = completion.usage
        row |= {
            "ms": _ms(started),
            "in": getattr(usage, "prompt_tokens", 0) or 0,
            "out": getattr(usage, "completion_tokens", 0) or 0,
            "cached": getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0) or 0,
            "reasoning": getattr(getattr(usage, "completion_tokens_details", None), "reasoning_tokens", 0) or 0,
        }
        _local.requests.append(row)
        return completion


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _won(requests: list[dict[str, Any]]) -> float:
    cost = 0.0
    for r in requests:
        fresh = r.get("in", 0) - r.get("cached", 0)
        cost += fresh * PRICE_IN + r.get("cached", 0) * PRICE_CACHED + r.get("out", 0) * PRICE_OUT
    return cost / 1_000_000


def _totals(requests: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "requests": len(requests),
        "in": sum(r.get("in", 0) for r in requests), "out": sum(r.get("out", 0) for r in requests),
        "cached": sum(r.get("cached", 0) for r in requests), "reasoning": sum(r.get("reasoning", 0) for r in requests),
        "won": _won(requests),
    }


# ---------------------------------------------------------------- 한 번 돌리기

def run_diagnosis(case: dict[str, Any], run: int) -> dict[str, Any]:
    world = fx.build(case)
    expect = case["expect"]
    key = expect["target"]
    inp = world.diagnosis_input(key)
    tools = fx.FixtureTools(world, DIAGNOSIS_TOOLS[inp["diagnosis"]])
    _local.requests = []
    started = time.monotonic()
    reply = service.agent_diagnose(inp, tool_runner=tools.run, planner=service.real_diagnosis_planner)
    ms = _ms(started)
    out = reply.result
    row: dict[str, Any] = {
        "case": case["id"], "run": run, "ms": ms, **_totals(_local.requests),
        "tools": [c["name"] for c in tools.calls], "expected_decision": expect["decision"],
        "request_errors": [{k: r[k] for k in ("error", "error_detail") if k in r} for r in _local.requests if "error" in r],
    }
    if isinstance(out, AgentCallFailed):
        return row | {"decision": None, "outcome": core.failed_outcome(out.reason), "failure": out.detail,
                      "decision_match": False, "button_match": False, "kept_actions": []}
    verified = fx.verify(world, key, out, tools)
    raw_text = " ".join(a.text for a in out.advice)
    row |= {
        "decision": out.decision,
        "outcome": verified.outcome,
        "verification": verified.record,
        "raw_actions": [a.type for a in out.actions],
        "raw_advice": [{"text": a.text, "is_guess": a.is_guess, "basis": a.basis} for a in out.advice],
        "raw_claims": [c.model_dump() for c in out.claims],
        "raw_forbidden": [w for w in FORBIDDEN_RAW if w in raw_text.replace(" ", "")],
    }
    expected_silent = expect["decision"] == "silent"
    row["decision_match"] = (out.decision != "suggest") if expected_silent else (out.decision == "suggest")
    draft = verified.draft
    if draft is not None:
        claims = {c["id"]: c for c in draft.claims}
        refs = core.RenderRefs(pin_names=world.names,
                               reaction_texts={r.reaction_id: r.text for r in world.snap.reasons if r.text})
        row["kept_actions"] = [a["type"] for a in draft.actions]
        row["rendered"] = [
            {"text": core.render_text(line["slot_text"], claims, refs), "is_guess": line["is_guess"]}
            for line in draft.advice
        ]
    else:
        row["kept_actions"] = []
    if expected_silent:
        row["button_match"] = row["decision_match"]
    else:
        row["button_match"] = bool(row["kept_actions"]) and row["kept_actions"][0] in expect["actions"]
    return row


def run_advice(world: fxa.AdviceWorld, run: int) -> dict[str, Any]:
    """조언 한 번(agent.flows.advise_run의 미리 읽기 → 모델 → 검증). patched_recommend_api() 안에서 부른다."""
    expect = world.case["expect"]
    ctx = world.tool_context()
    inp = world.advice_input(ctx)
    _local.requests = []
    started = time.monotonic()
    reply = service.agent_advise_run(inp, tool_runner=ctx.run, planner=service.real_advice_planner)
    ms = _ms(started)
    out = reply.result
    model_calls = [c for c in ctx.calls if not c.get("prefetched")]
    row: dict[str, Any] = {
        "case": world.case["id"], "run": run, "ms": ms, **_totals(_local.requests),
        "tools": [c["name"] for c in model_calls],
        "radius_factors": [c["args"].get("radius_factor") for c in model_calls
                           if c["name"] == "simulate_filter" and c["args"].get("radius_factor") is not None],
        "next_radius_factor": inp["radius"]["next_radius_factor"],
        "expected_decision": expect["decision"], "expected_kinds": expect["kinds"],
        "request_errors": [{k: r[k] for k in ("error", "error_detail") if k in r} for r in _local.requests if "error" in r],
    }
    if isinstance(out, AgentCallFailed):
        return row | {"decision": None, "kind": None, "outcome": core.failed_outcome(out.reason), "failure": out.detail,
                      "decision_match": False, "kind_match": False, "button_match": False, "kept_actions": [],
                      "other_buttons_raw": 0, "other_buttons_kept": 0}
    verified = world.verify(out, ctx)
    squashed = " ".join(a.text for a in out.advice).replace(" ", "")
    local = {v: k for k, v in world.local_ids.items()}
    own = {line["line_id"] for line in world.lines if line["author_id"] == fxa.REQUESTER}
    kept = [{"type": a["type"], "lines": sorted(local[i] for i in a["params"].get("evidence_line_ids", []))}
            for a in verified.draft.actions]
    removed = (verified.record.get("actions") or {}).get("removed", [])
    row |= {
        "decision": out.decision, "kind": out.kind, "outcome": verified.outcome, "verification": verified.record,
        "raw_actions": [{"type": a.type, "basis": a.basis} for a in out.actions],
        "raw_advice": [{"text": a.text, "is_guess": a.is_guess, "basis": a.basis} for a in out.advice],
        "raw_claims": [c.model_dump() for c in out.claims],
        "raw_forbidden": [w for w in FORBIDDEN_RAW if w in squashed],
        "raw_relax": [w for w in RELAX_RAW if w in squashed],
        "raw_not_filtered": [w for w in NOT_FILTERED_RAW if w in squashed],
        "kept_actions": kept,
        "other_buttons_raw": sum(r["reason"] == "not_own_line" for r in removed),
        "other_buttons_kept": sum(any(world.line_id(i) not in own for i in a["lines"]) for a in kept),
    }
    shown = world.render(verified.draft)
    row["rendered"] = [{"text": a.text, "is_guess": a.is_guess} for a in shown.advice] if shown else []
    if expect["decision"] == "silent":
        row["decision_match"] = row["kind_match"] = out.decision != "suggest"
        row["button_match"] = not kept
    else:
        row["decision_match"] = out.decision == "suggest"
        row["kind_match"] = out.decision == "suggest" and out.kind in expect["kinds"]
        allowed = set(expect.get("button_lines", []))
        lines = {i for a in kept for i in a["lines"]}
        row["button_match"] = (verified.outcome == "advised" and {a["type"] for a in kept} == set(expect["buttons"])
                               and lines <= allowed and bool(lines) == bool(allowed))
    return row


# ---------------------------------------------------------------- 요약

def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "-"


def _avg(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def _p(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def summarize(cases: list[dict[str, Any]], diag: list[dict[str, Any]]) -> str:
    lines = [f"# agent 진단 평가 — {datetime.now().isoformat(timespec='seconds')}",
             "", f"모델 {settings.llm_model}, 프롬프트 {AGENT_DIAGNOSE_PROMPT_VERSION}", ""]

    if diag:
        suggest_rows = [r for r in diag if r.get("decision") == "suggest"]
        passed = [r for r in suggest_rows if r["outcome"] == "suggested"]
        lines += ["## 진단 (reasoning_effort=none 고정)", "",
                  "| 지표 | 값 |", "|---|---|",
                  f"| 호출 | {len(diag)} |",
                  f"| 호출 실패(model_failed, invalid_schema) | {_pct(sum(r['outcome'] in ('model_failed', 'invalid_schema') for r in diag), len(diag))} |",
                  f"| 결정(suggest/silent) 일치 | {_pct(sum(r['decision_match'] for r in diag), len(diag))} |",
                  f"| 검증 통과(suggest 중 초안이 남음) | {_pct(len(passed), len(suggest_rows))} |",
                  f"| 고른 버튼 일치(첫 버튼, 침묵 기대는 침묵) | {_pct(sum(r['button_match'] for r in diag), len(diag))} |",
                  f"| 원문에 결정 지시 표현 | {sum(bool(r.get('raw_forbidden')) for r in diag)} |",
                  f"| 도구 호출 수(평균, 최대) | {_avg([len(r['tools']) for r in diag]):.1f}, {max(len(r['tools']) for r in diag)} |",
                  f"| 모델 요청 수(평균) | {_avg([r['requests'] for r in diag]):.1f} |",
                  f"| 입력 토큰(평균, 캐시) | {_avg([r['in'] for r in diag]):.0f} ({_avg([r['cached'] for r in diag]):.0f}) |",
                  f"| 출력 토큰(평균) | {_avg([r['out'] for r in diag]):.0f} |",
                  f"| 시간 ms(평균, p90, 최대) | {_avg([r['ms'] for r in diag]):.0f}, {_p([r['ms'] for r in diag], 0.9):.0f}, {max(r['ms'] for r in diag)} |",
                  f"| 진단당 원 | {_avg([r['won'] for r in diag]):.3f} |"]
        steps: Counter = Counter()
        for r in suggest_rows:
            v = r.get("verification") or {}
            if v.get("failed_step"):
                steps[f"성립 실패 {v['failed_step']}단계"] += 1
            for c in (v.get("claims") or {}).get("removed", []):
                steps[f"claim 제거: {c['reason']}"] += 1
            for c in (v.get("lines") or {}).get("removed", []):
                steps[f"문장 제거: {c['reason']}"] += 1
            for c in (v.get("actions") or {}).get("removed", []):
                steps[f"행동 제거: {c['reason']}"] += 1
        lines += ["", "단계별 탈락 사유(suggest 호출에서 센 횟수)", "", "| 사유 | 횟수 |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in steps.most_common()] or ["| 없음 | 0 |"]
        lines += ["", "케이스별", "", "| 케이스 | 기대 결정/버튼 | 결정 일치 | 검증 통과 | 버튼 일치 | 고른 첫 버튼 | 도구 | 평균 ms |",
                  "|---|---|---|---|---|---|---|---|"]
        by_case = defaultdict(list)
        for r in diag:
            by_case[r["case"]].append(r)
        expect = {c["id"]: c["expect"] for c in cases}
        for cid, rows in by_case.items():
            e = expect[cid]
            sug = [r for r in rows if r.get("decision") == "suggest"]
            firsts = Counter((r.get("kept_actions") or ["-"])[0] for r in rows)
            tools = Counter("+".join(r["tools"]) or "-" for r in rows).most_common(1)[0][0]
            lines.append(
                f"| {cid} | {e['decision']}/{'|'.join(e['actions']) or '-'} | {sum(r['decision_match'] for r in rows)}/{len(rows)} "
                f"| {sum(r['outcome'] == 'suggested' for r in sug)}/{len(sug)} | {sum(r['button_match'] for r in rows)}/{len(rows)} "
                f"| {', '.join(f'{k}×{v}' for k, v in firsts.items())} | {tools} | {_avg([r['ms'] for r in rows]):.0f} |")
        lines += ["", "렌더 예시(케이스마다 처음 통과한 것)", ""]
        for cid, rows in by_case.items():
            good = next((r for r in rows if r.get("rendered")), None)
            if good:
                texts = " / ".join(f"{x['text']}{' (짐작)' if x['is_guess'] else ''}" for x in good["rendered"])
                lines.append(f"- {cid}: [{', '.join(good['kept_actions'])}] {texts}")
    return "\n".join(lines) + "\n"


def _removed_steps(rows: list[dict[str, Any]]) -> Counter:
    steps: Counter = Counter()
    for r in rows:
        v = r.get("verification") or {}
        if v.get("failed_step"):
            steps[f"성립 실패 {v['failed_step']}단계"] += 1
        for part, name in (("claims", "claim"), ("lines", "문장"), ("actions", "버튼")):
            for c in (v.get(part) or {}).get("removed", []):
                steps[f"{name} 제거: {c['reason']}"] += 1
    return steps


def summarize_advice(cases: list[dict[str, Any]], rows: list[dict[str, Any]]) -> str:
    lines = [f"# agent 추천 막힘 조언 평가 — {datetime.now().isoformat(timespec='seconds')}",
             "", f"모델 {settings.llm_model}, 프롬프트 {AGENT_ADVISE_RUN_PROMPT_VERSION}", ""]
    if not rows:
        return "\n".join(lines) + "\n"
    suggest_rows = [r for r in rows if r.get("decision") == "suggest"]
    expect_suggest = [r for r in rows if r["expected_decision"] == "suggest"]
    factors = [(f, r["next_radius_factor"]) for r in rows for f in r.get("radius_factors", [])]
    lines += ["## 조언 (reasoning_effort=none 고정)", "",
              "| 지표 | 값 |", "|---|---|",
              f"| 호출 | {len(rows)} |",
              f"| 호출 실패(model_failed, invalid_schema) | {_pct(sum(r['outcome'] in ('model_failed', 'invalid_schema') for r in rows), len(rows))} |",
              f"| 결정(suggest/silent) 일치 | {_pct(sum(r['decision_match'] for r in rows), len(rows))} |",
              f"| 검증 통과(suggest 중 조언이 남음) | {_pct(sum(r['outcome'] == 'advised' for r in suggest_rows), len(suggest_rows))} |",
              f"| 종류 일치(제안 기대 중) | {_pct(sum(r['kind_match'] for r in expect_suggest), len(expect_suggest))} |",
              f"| 버튼 일치(검증 뒤, 침묵 기대는 버튼 없음) | {_pct(sum(r['button_match'] for r in rows), len(rows))} |",
              f"| 남의 줄 버튼: 모델 원문(검증이 뺌) / 검증 뒤 | {sum(r['other_buttons_raw'] for r in rows)} / {sum(r['other_buttons_kept'] for r in rows)} |",
              f"| 원문에 결정 지시 표현 | {sum(bool(r.get('raw_forbidden')) for r in rows)} |",
              f"| 원문에 완화 명령형(빼세요, 넓히세요 등) | {sum(bool(r.get('raw_relax')) for r in rows)} |",
              f"| 원문에 알러지·가격 언급 | {sum(bool(r.get('raw_not_filtered')) for r in rows)} |",
              f"| 반경 시뮬레이션 중 버튼 한 번의 배율 | {sum(n is not None and abs(f - n) < 1e-9 for f, n in factors)}/{len(factors)} |",
              f"| 도구 호출 수(평균, 최대) | {_avg([len(r['tools']) for r in rows]):.1f}, {max(len(r['tools']) for r in rows)} |",
              f"| 모델 요청 수(평균) | {_avg([r['requests'] for r in rows]):.1f} |",
              f"| 입력 토큰(평균, 캐시) | {_avg([r['in'] for r in rows]):.0f} ({_avg([r['cached'] for r in rows]):.0f}) |",
              f"| 출력 토큰(평균) | {_avg([r['out'] for r in rows]):.0f} |",
              f"| 시간 ms(평균, p90, 최대) | {_avg([r['ms'] for r in rows]):.0f}, {_p([r['ms'] for r in rows], 0.9):.0f}, {max(r['ms'] for r in rows)} |",
              f"| 조언당 원 | {_avg([r['won'] for r in rows]):.3f} |"]
    lines += ["", "단계별 탈락 사유(suggest 호출에서 센 횟수)", "", "| 사유 | 횟수 |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in _removed_steps(suggest_rows).most_common()] or ["| 없음 | 0 |"]
    lines += ["", "케이스별", "",
              "| 케이스 | 기대 결정/종류/버튼 | 결정 | 종류 | 검증 통과 | 버튼 | 고른 종류 | 남은 버튼 | 도구 | 평균 ms |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    by_case = defaultdict(list)
    for r in rows:
        by_case[r["case"]].append(r)
    expect = {c["id"]: c["expect"] for c in cases}
    for cid, rs in by_case.items():
        e = expect[cid]
        sug = [r for r in rs if r.get("decision") == "suggest"]
        kinds = Counter(r.get("kind") if r.get("decision") == "suggest" else (r.get("decision") or "실패") for r in rs)
        buttons = Counter("+".join(a["type"] + (f"({','.join(a['lines'])})" if a["lines"] else "")
                                   for a in r.get("kept_actions", [])) or "-" for r in rs)
        tools = Counter("+".join(r["tools"]) or "-" for r in rs).most_common(1)[0][0]
        lines.append(
            f"| {cid} | {e['decision']}/{'|'.join(e['kinds']) or '-'}/{'|'.join(e['buttons']) or '-'} "
            f"| {sum(r['decision_match'] for r in rs)}/{len(rs)} | {sum(r['kind_match'] for r in rs)}/{len(rs)} "
            f"| {sum(r['outcome'] == 'advised' for r in sug)}/{len(sug)} | {sum(r['button_match'] for r in rs)}/{len(rs)} "
            f"| {', '.join(f'{k}×{v}' for k, v in kinds.items())} | {', '.join(f'{k}×{v}' for k, v in buttons.items())} "
            f"| {tools} | {_avg([r['ms'] for r in rs]):.0f} |")
    lines += ["", "렌더 예시(케이스마다 처음 남은 것)", ""]
    for cid, rs in by_case.items():
        good = next((r for r in rs if r.get("rendered")), None)
        if good:
            texts = " / ".join(f"{x['text']}{' (짐작)' if x['is_guess'] else ''}" for x in good["rendered"])
            names = ", ".join(a["type"] for a in good["kept_actions"])
            lines.append(f"- {cid}: [{names}] {texts}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=("diagnosis", "advice"), default="diagnosis")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--cases", default="")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--tag", default="")
    parser.add_argument("--summarize", default="", help="저장된 결과 JSON으로 요약만 다시 낸다(모델을 부르지 않는다)")
    args = parser.parse_args()

    if args.summarize:
        saved = json.loads(Path(args.summarize).read_text(encoding="utf-8"))
        if "advice" in saved:
            report = summarize_advice(fxa.load_cases(), saved["advice"])
        else:
            report = summarize(fx.load_cases(), saved["diagnosis"])
        Path(args.summarize).with_suffix(".md").write_text(report, encoding="utf-8")
        print(report)
        return 0

    if not (settings.elice_ml_api_base_url and settings.elice_ml_api_key):
        print("ELICE_ML_API_BASE_URL / ELICE_ML_API_KEY가 없다", file=sys.stderr)
        return 2
    llm_client._client = RecordingClient(llm_client.make_client())
    if args.target == "advice":
        return _main_advice(args)

    cases = fx.load_cases()
    if args.cases:
        wanted = set(args.cases.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    jobs = [(c, i) for c in cases if c["expect"]["target"] for i in range(args.runs)]

    started = time.monotonic()

    def go(job):
        case, i = job
        try:
            return run_diagnosis(case, i)
        except Exception as exc:  # noqa: BLE001 — 평가 도구. 한 건이 실패해도 나머지를 본다
            return {"case": case["id"], "run": i, "crash": type(exc).__name__}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        done = list(pool.map(go, jobs))
    diag = [r for r in done if "crash" not in r]
    crashes = [r for r in done if "crash" in r]

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}-{AGENT_DIAGNOSE_PROMPT_VERSION}{('-' + args.tag) if args.tag else ''}"
    (RESULTS_DIR / f"{name}.json").write_text(
        json.dumps({"diagnosis": diag, "crashes": crashes}, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")
    report = summarize(cases, diag)
    report += f"\n총 {len(jobs)}건, 크래시 {len(crashes)}, 걸린 시간 {time.monotonic() - started:.0f}초\n"
    (RESULTS_DIR / f"{name}.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"저장: {RESULTS_DIR / name}.json, .md")
    return 0


def _main_advice(args: argparse.Namespace) -> int:
    cases = fxa.load_cases()
    if args.cases:
        wanted = set(args.cases.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    worlds = [fxa.build(c) for c in cases]
    jobs = [(w, i) for w in worlds for i in range(args.runs)]
    started = time.monotonic()

    def go(job):
        world, i = job
        try:
            return run_advice(world, i)
        except Exception as exc:  # noqa: BLE001 — 평가 도구. 한 건이 실패해도 나머지를 본다
            return {"case": world.case["id"], "run": i, "crash": type(exc).__name__}

    with fxa.patched_recommend_api(worlds), ThreadPoolExecutor(max_workers=args.workers) as pool:
        done = list(pool.map(go, jobs))
    rows = [r for r in done if "crash" not in r]
    crashes = [r for r in done if "crash" in r]

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}-{AGENT_ADVISE_RUN_PROMPT_VERSION}{('-' + args.tag) if args.tag else ''}"
    (RESULTS_DIR / f"{name}.json").write_text(
        json.dumps({"advice": rows, "crashes": crashes}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    report = summarize_advice(cases, rows)
    report += f"\n총 {len(jobs)}건, 크래시 {len(crashes)}, 걸린 시간 {time.monotonic() - started:.0f}초\n"
    (RESULTS_DIR / f"{name}.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"저장: {RESULTS_DIR / name}.json, .md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
