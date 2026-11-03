"""웹 확인 평가(#1216, docs/agent-v2.md 6.8 「평가」) — web_cases.json의 가게 10곳을 실제 모델(Responses API + web_search)로 N번씩 돌려 표를 낸다.

    cd backend
    python -m llm.tests.eval_agent.run_web_eval                    # 10개 × 3회(한 번 약 30원)
    python -m llm.tests.eval_agent.run_web_eval --runs 1 --cases w07_missing_kalguksu
    python -m llm.tests.eval_agent.run_web_eval --cases w09_same_name_gukbap --city-sido   # 검색 위치를 장소의 시·도로(#1221 비교)

- 돌리기 전에 케이스 수와 예상 비용을 사용자에게 보고하고 확인을 받는다(#1216). 키는 backend/.env의 설정(settings)으로만 읽고
  출력하거나 파일에 쓰지 않는다.
- 호출과 검증은 운영과 같은 llm.service.web_check + real_web_check_planner + agent.core.WEB_CHECK_FORBIDDEN이다. 서비스 일일 예산은
  보지 않는다(평가는 운영 비용이 아니다 — usage.spent_reader를 0으로 바꾼다). usage_context로 감싸지 않아 llm_calls에 남지 않는다.
- 본다(6.8): 출처 대조 통과율(모델이 쓴 문장 중 출처가 그 호출의 검색 결과에 있는 비율), 없는 가게 not_found 비율, 검증으로 빠진 문장
  수와 이유, 결론·권유 표현(검증 전 모델 원문), 다른 동네 가게 글(사람이 읽고 센다 — 결과 Markdown에 문장과 출처를 적는다), 검색 횟수,
  시간, 비용(토큰 + 검색 × LLM_PRICE_WEB_SEARCH_KRW).
- 결과는 results/(커밋하지 않는다)에 JSON(호출마다)과 Markdown(요약표, 사람이 읽을 문장 목록)으로 남긴다. 입력은 장소 이름·동네·특징 이름뿐이다.
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
from llm import service, usage
from llm.prompts import WEB_CHECK_PROMPT_VERSION
from llm.tests.eval_agent.run_eval import RESULTS_DIR
from places import api as places_api

CASES_PATH = Path(__file__).with_name("web_cases.json")
COST_PER_CALL_KRW = 30   # 6.8 「한 번에 보통 약 30원」(2026-11-03 실험) — 돌리기 전 보고용 어림
_local = threading.local()


def load_cases() -> list[dict[str, Any]]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


class RecordingResponses:
    """responses.create 감싸개 — 요청마다 시간, 토큰, 검색 횟수를 스레드별로 남긴다. 본문은 남기지 않는다."""

    def __init__(self, inner: Any):
        self._inner = inner
        self.responses = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: Any) -> Any:
        started = time.monotonic()
        row: dict[str, Any] = {}
        try:
            response = self._inner.responses.create(**kwargs)
        except Exception as exc:
            row |= {"ms": int((time.monotonic() - started) * 1000), "error": type(exc).__name__}
            _local.requests.append(row)
            raise
        counts = usage.token_counts(response)
        searches = len(llm_client._web_search_calls(response))
        row |= {"ms": int((time.monotonic() - started) * 1000), "input": counts.input_tokens,
                "cached": counts.cached_input_tokens, "output": counts.output_tokens, "web_searches": searches,
                "cost_krw": usage.cost_krw(counts, web_searches=searches)}
        _local.requests.append(row)
        return response


def run_case(client: Any, case: dict[str, Any], run: int, *, city_sido: bool = False) -> dict[str, Any]:
    _local.requests = []
    raw: dict[str, Any] = {}
    city = places_api.sido(case["address"]) if city_sido else None   # None이면 운영과 같은 서울

    def planner(check_input):
        answer = llm_client.call_web_check(client, check_input, city=city)
        raw["answer"] = answer
        return answer

    started = time.monotonic()
    result = service.web_check(place_name=case["place_name"], area=case["area"], feature=case["feature"],
                               forbidden=core.WEB_CHECK_FORBIDDEN, planner=planner)
    req = _local.requests[0] if _local.requests else {}
    row: dict[str, Any] = {
        "case": case["id"], "kind": case["kind"], "run": run, "city": city or llm_client.WEB_SEARCH_CITY,
        "ms": int((time.monotonic() - started) * 1000),
        "status": result.status, "detail": result.detail, "dropped": list(result.dropped),
        "web_searches": req.get("web_searches", result.web_searches), "cost_krw": req.get("cost_krw", 0.0),
        "tokens": {k: req.get(k, 0) for k in ("input", "cached", "output")},
        "statements": [{"text": s.text, "source_url": s.source_url, "source_name": s.source_name} for s in result.statements],
    }
    answer = raw.get("answer")
    if answer is not None:
        listed = {service._url_key(u) for u in answer.sources}
        model_statements = answer.output.statements if answer.output.status == "found" else []
        row |= {
            "model_status": answer.output.status,
            "sources": len(answer.sources),
            "model_statements": [{"text": s.text, "source_url": s.source_url} for s in model_statements],
            "source_ok": sum(service._url_key(s.source_url) in listed for s in model_statements),
            "conclusion": sum(any(p.replace(" ", "") in s.text.replace(" ", "") for p in core.WEB_CHECK_FORBIDDEN)
                              for s in model_statements),
        }
    return row


def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({n / d:.0%})" if d else "0/0"


def summarize(rows: list[dict[str, Any]], cases: list[dict[str, Any]]) -> str:
    by_case = {c["id"]: c for c in cases}
    lines = [f"# 웹 확인 평가 — {datetime.now().isoformat(timespec='seconds')}", "",
             f"모델 {settings.llm_model}, 프롬프트 {WEB_CHECK_PROMPT_VERSION}, Responses API + web_search, reasoning none, "
             f"max_tool_calls=1, 검색 위치 {sorted({r['city'] for r in rows})}, 케이스 {len(cases)} × {max(r['run'] for r in rows) + 1}회", ""]
    answered = [r for r in rows if "model_statements" in r]
    written = sum(len(r["model_statements"]) for r in answered)
    missing = [r for r in rows if r["kind"] == "missing"]
    dropped = Counter(d for r in rows for d in r["dropped"])
    ms = [r["ms"] for r in rows]
    searches = [r["web_searches"] for r in rows]
    cost = sum(r["cost_krw"] for r in rows)
    lines += [
        "| 지표 | 값 |", "|---|---|",
        f"| 결과 | {dict(Counter(r['status'] for r in rows))} |",
        f"| 출처 대조 통과(모델이 쓴 문장) | {_pct(sum(r['source_ok'] for r in answered), written)} |",
        f"| 없는 가게 not_found | {_pct(sum(r['status'] == 'not_found' for r in missing), len(missing))} |",
        f"| 검증으로 빠진 문장 | {sum(dropped.values())} {dict(dropped)} |",
        f"| 결론·권유 표현(모델 원문) | {sum(r.get('conclusion', 0) for r in answered)} |",
        f"| 검색 횟수 | 평균 {statistics.mean(searches):.2f}, 분포 {dict(Counter(searches))} |",
        f"| 시간 | 중앙 {statistics.median(ms) / 1000:.1f}초, 최대 {max(ms) / 1000:.1f}초 |",
        f"| 비용 | 합계 {cost:.0f}원, 1번 평균 {cost / len(rows):.1f}원 |",
        "", "## 케이스별", "", "| 케이스 | 종류 | 기대 | 결과 | 빠진 문장 | 검색 |", "|---|---|---|---|---|---|",
    ]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        grouped[r["case"]].append(r)
    for cid, rs in grouped.items():
        lines.append(f"| {cid} | {rs[0]['kind']} | {by_case[cid]['expect']} | {', '.join(r['status'] for r in rs)} | "
                     f"{sum(len(r['dropped']) for r in rs)} | {', '.join(str(r['web_searches']) for r in rs)} |")
    lines += ["", "## 화면에 나갈 문장(사람이 읽는다 — 다른 동네 가게 글인지, 판정·권유가 섞였는지)", ""]
    for cid, rs in grouped.items():
        case = by_case[cid]
        lines.append(f"### {cid} — {case['place_name']} / {case['area']} / {case['feature']}")
        if case.get("other_areas"):
            lines.append(f"다른 동네(쓰면 안 됨): {', '.join(case['other_areas'])}")
        for r in rs:
            shown = "; ".join(f"「{s['text']}」 ({s['source_name']})" for s in r["statements"]) or "-"
            lines.append(f"- run {r['run']}: {r['status']} — {shown}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--cases", nargs="*")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--city-sido", action="store_true", help="검색 위치 city를 장소 주소의 시·도로(기본은 운영과 같은 서울)")
    args = parser.parse_args(argv)

    cases = [c for c in load_cases() if not args.cases or c["id"] in args.cases]
    print(f"케이스 {len(cases)} × {args.runs}회 = {len(cases) * args.runs}번, 예상 약 {len(cases) * args.runs * COST_PER_CALL_KRW}원")
    usage.spent_reader = lambda since: 0.0   # 평가는 서비스 일일 예산을 보지 않는다(위 설명)
    client = RecordingResponses(llm_client.get_client())
    jobs = [(c, r) for c in cases for r in range(args.runs)]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(lambda job: run_case(client, *job, city_sido=args.city_sido), jobs))

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (RESULTS_DIR / f"web-{stamp}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    report = summarize(rows, cases)
    (RESULTS_DIR / f"web-{stamp}.md").write_text(report, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
