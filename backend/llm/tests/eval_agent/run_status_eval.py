"""지도 현황 문단 평가(#1168, docs/agent-v2.md 8.2 「평가」) — status_cases.json의 상황 10개를 실제 모델로 N번씩 돌려 표를 낸다.

    cd backend
    python -m llm.tests.eval_agent.run_status_eval                  # 10개 × 5회
    python -m llm.tests.eval_agent.run_status_eval --runs 1 --cases s01_example_1152

- 키는 backend/.env의 ELICE_ML_API_BASE_URL, ELICE_ML_API_KEY(settings)로만 읽는다. 키와 URL을 출력하거나 파일에 쓰지 않는다.
- 호출은 운영과 같은 llm.service.agent_status + real_status_planner(구조화 출력, reasoning_effort=none, 도구 없음)다.
- 검증은 운영과 같은 agent.core.verify_status다. 기준(8.2): 상태가 사실과 모순 0, 칸 밖 숫자 0, first_category 언급.
  그 밖에 카테고리 빠뜨림, 다른 카테고리를 먼저 권함, 금지 표현, 기대 상태 일치(참고), 문장 수(2~4, 모두 정해지면 1)를 센다.
- 칸에는 사유 글, 이름, 장소 이름이 없다. 결과는 results/(커밋하지 않는다)에 JSON(호출마다 원본)과 Markdown(요약표)으로 남긴다.
"""

import argparse
import json
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from agent import core
from common.settings import settings
from llm import client as llm_client
from llm import service
from llm.prompts import AGENT_STATUS_PROMPT_VERSION
from llm.schemas import AgentCallFailed
from llm.tests.eval_agent.run_eval import RESULTS_DIR, RecordingClient, _local, _ms, _p, _pct, _totals

CASES_PATH = Path(__file__).with_name("status_cases.json")
CHECKS = ("categories", "states", "numbers", "first_category", "forbidden")


def load_cases() -> list[dict[str, Any]]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def _sentences(paragraph: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?])\s+", paragraph.strip()) if s])


def run_status(case: dict[str, Any], run: int) -> dict[str, Any]:
    cells = case["cells"]
    _local.requests = []
    started = time.monotonic()
    reply = service.agent_status(cells, planner=service.real_status_planner)
    row: dict[str, Any] = {"case": case["id"], "run": run, "ms": _ms(started), **_totals(_local.requests)}
    out = reply.result
    if isinstance(out, AgentCallFailed):
        return row | {"outcome": core.failed_outcome(out.reason), "failure": out.detail, "failed": ["call"]}
    verified = core.verify_status(out, cells)
    expect = case["expect_states"]
    states = {c.category: c.state for c in out.categories}
    all_decided = all(allowed == ["decided"] for allowed in expect.values())
    n = _sentences(out.paragraph)
    return row | {
        "outcome": "status_updated" if verified.ok else "invalid_claims",
        "failed": verified.record["failed"],
        "verification": verified.record,
        "paragraph": out.paragraph,
        "states": states,
        "state_match": sum(states.get(c) in allowed for c, allowed in expect.items()),
        "state_total": len(expect),
        "first_mentioned": cells["first_category"] is None or cells["first_category"] in out.paragraph,
        "sentences": n,
        "sentence_ok": n == 1 if all_decided else 2 <= n <= 4,
    }


def summarize(rows: list[dict[str, Any]]) -> str:
    lines = [f"# 지도 현황 문단 평가 — {datetime.now().isoformat(timespec='seconds')}", "",
             f"모델 {settings.llm_model}, 프롬프트 {AGENT_STATUS_PROMPT_VERSION}, reasoning_effort=none, 도구 없음", ""]
    ok = [r for r in rows if r["outcome"] == "status_updated"]
    answered = [r for r in rows if "states" in r]
    failed = Counter(f for r in rows for f in r["failed"])
    lines += ["| 지표 | 값 |", "|---|---|",
              f"| 호출 | {len(rows)} |",
              f"| 검증 통과(저장됨) | {_pct(len(ok), len(rows))} |",
              f"| 호출 실패 | {failed.get('call', 0)} |",
              *[f"| 걸림: {c} | {failed.get(c, 0)} |" for c in CHECKS],
              f"| first_category 언급 | {_pct(sum(r['first_mentioned'] for r in answered), len(answered))} |",
              f"| 기대 상태 일치(참고, 카테고리 단위) | {_pct(sum(r['state_match'] for r in answered), sum(r['state_total'] for r in answered))} |",
              f"| 문장 수 규칙(2~4, 모두 정해지면 1) | {_pct(sum(r['sentence_ok'] for r in answered), len(answered))} |",
              f"| 입력·출력 토큰(평균) | {statistics.mean(r['in'] for r in rows):.0f} · {statistics.mean(r['out'] for r in rows):.0f} |",
              f"| 시간 ms(평균, p90, 최대) | {statistics.mean(r['ms'] for r in rows):.0f}, {_p([r['ms'] for r in rows], 0.9):.0f}, {max(r['ms'] for r in rows)} |",
              f"| 호출당 원 | {statistics.mean(r['won'] for r in rows):.3f} |"]
    by_case = defaultdict(list)
    for r in rows:
        by_case[r["case"]].append(r)
    lines += ["", "케이스별", "", "| 케이스 | 통과 | 걸린 검사 | 상태 일치 | 문장 수 |", "|---|---|---|---|---|"]
    for cid, rs in by_case.items():
        checks = Counter(f for r in rs for f in r["failed"])
        lines.append(f"| {cid} | {sum(r['outcome'] == 'status_updated' for r in rs)}/{len(rs)} "
                     f"| {', '.join(f'{k}×{v}' for k, v in checks.items()) or '-'} "
                     f"| {sum(r.get('state_match', 0) for r in rs)}/{sum(r.get('state_total', 0) for r in rs)} "
                     f"| {', '.join(str(r.get('sentences', '-')) for r in rs)} |")
    lines += ["", "문단 예시(케이스마다 처음 통과한 것, 없으면 처음 것)", ""]
    for cid, rs in by_case.items():
        pick = next((r for r in rs if r["outcome"] == "status_updated"), rs[0])
        if "paragraph" in pick:
            lines.append(f"- {cid} [{pick['outcome']}]: {pick['paragraph']}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--cases", default="")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--tag", default="")
    args = parser.parse_args()

    if not (settings.elice_ml_api_base_url and settings.elice_ml_api_key):
        print("ELICE_ML_API_BASE_URL / ELICE_ML_API_KEY가 없다", file=sys.stderr)
        return 2
    llm_client._client = RecordingClient(llm_client.make_client())

    cases = load_cases()
    if args.cases:
        wanted = set(args.cases.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    jobs = [(c, i) for c in cases for i in range(args.runs)]
    started = time.monotonic()

    def go(job):
        case, i = job
        try:
            return run_status(case, i)
        except Exception as exc:  # noqa: BLE001 — 평가 도구. 한 건이 실패해도 나머지를 본다
            return {"case": case["id"], "run": i, "crash": type(exc).__name__}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        done = list(pool.map(go, jobs))
    rows = [r for r in done if "crash" not in r]
    crashes = [r for r in done if "crash" in r]

    RESULTS_DIR.mkdir(exist_ok=True)
    name = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{AGENT_STATUS_PROMPT_VERSION}{('-' + args.tag) if args.tag else ''}"
    (RESULTS_DIR / f"{name}.json").write_text(
        json.dumps({"status": rows, "crashes": crashes}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    report = summarize(rows) if rows else "결과 없음\n"
    report += f"\n총 {len(jobs)}건, 크래시 {len(crashes)}, 걸린 시간 {time.monotonic() - started:.0f}초\n"
    (RESULTS_DIR / f"{name}.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"저장: {RESULTS_DIR / name}.json, .md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
