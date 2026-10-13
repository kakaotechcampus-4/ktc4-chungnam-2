"""매칭률 측정(#500) — 표본 검색어로 장소 검색을 돌려 pinnable 비율을 [주소 보조 전/후]로 낸다.

    python -m places.scripts.measure_match_rate [--queries 200] [--limit 15] [--out rates.json]

카카오를 검색어마다 한 번 부른다(PLACES_MODE=prod, KAKAO_REST_API_KEY 필요). 카카오 응답은 메모리에서 이 함수 안에만
머물다 사라진다 — 출력(화면·--out 파일)은 건수와 비율뿐이고 이름·좌표·주소는 어디에도 쓰지 않는다(#53).
자체 DB(#499 적재 전후)를 바꾼 뒤 같은 명령으로 다시 돌려 비교한다.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from collections import Counter

from places import api
from places.schemas import PlaceHint, PlaceSearchResult

_AREAS = (
    "성수", "홍대", "연남", "망원", "합정", "이태원", "한남", "강남역", "신사", "압구정", "잠실", "건대", "종로", "익선동",
    "북촌", "을지로", "서촌", "여의도", "신촌", "명동", "서울숲", "뚝섬", "상수", "역삼", "광화문",
)
_KINDS = ("맛집", "카페", "칼국수", "파스타", "고깃집", "브런치", "디저트", "공원")   # 25 × 8 = 200


def sample_queries(n: int) -> list[str]:
    """지역 × 업종 조합을 결정적으로 n개 — 실행할 때마다 같은 표본이라 적재 전후를 비교할 수 있다."""
    return [f"{a} {k}" for a, k in itertools.islice(itertools.product(_AREAS, _KINDS), n)]


def _hint(r: PlaceSearchResult, *, with_address: bool) -> PlaceHint:
    # 핀 생성이 보내는 힌트와 같은 모양(places/router.py의 _fill_pinnable)에 주소만 켜고 끈다
    return PlaceHint(r.place_id, r.place_name, r.lat, r.lng, r.category or "", r.address if with_address else None)


def measure(queries: list[str], limit: int, pause_s: float) -> dict:
    total: Counter = Counter()
    for i, q in enumerate(queries):
        try:
            results = api.search_by_name(q, None, limit)
        except Exception as exc:   # noqa: BLE001 — 타입만 남긴다. 메시지에 카카오 값이 실릴 수 있다
            print(f"검색 실패({type(exc).__name__}): {i + 1}번째 검색어", file=sys.stderr)
            total["search_failed"] += 1
            continue
        if results:
            before = api.pinnable_flags([_hint(r, with_address=False) for r in results])
            after = api.pinnable_flags([_hint(r, with_address=True) for r in results])
            total["results"] += len(results)
            total["with_address"] += sum(1 for r in results if r.address)
            total["pinnable_before"] += sum(before)
            total["pinnable_after"] += sum(after)
            total["gained"] += sum(1 for b, a in zip(before, after) if a and not b)
            total["lost"] += sum(1 for b, a in zip(before, after) if b and not a)
        total["queries"] += 1
        if pause_s and i + 1 < len(queries):
            time.sleep(pause_s)
    return dict(total)


def report(t: dict) -> str:
    n = t.get("results", 0)

    def pct(k: str) -> str:
        v = t.get(k, 0)
        return f"{v}/{n} ({100 * v / n:.1f}%)" if n else f"{v}/0"

    return "\n".join([
        f"검색어 {t.get('queries', 0)}개 (실패 {t.get('search_failed', 0)}), 결과 {n}건, 주소 있는 결과 {t.get('with_address', 0)}건",
        f"pinnable [주소 보조 전]: {pct('pinnable_before')}",
        f"pinnable [주소 보조 후]: {pct('pinnable_after')}",
        f"주소로 새로 매칭 {t.get('gained', 0)}건 / 주소로 거절돼 사라짐 {t.get('lost', 0)}건",
    ])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--queries", type=int, default=200, help="표본 검색어 수(최대 200)")
    ap.add_argument("--limit", type=int, default=15, help="검색어당 결과 수(최대 15)")
    ap.add_argument("--pause", type=float, default=0.2, help="검색 사이 대기(초) — 카카오 쿼터 보호")
    ap.add_argument("--out", help="숫자만 담은 JSON 저장 경로(선택)")
    args = ap.parse_args(argv)
    totals = measure(sample_queries(min(args.queries, len(_AREAS) * len(_KINDS))), min(args.limit, 15), args.pause)
    print(report(totals))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(totals, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
