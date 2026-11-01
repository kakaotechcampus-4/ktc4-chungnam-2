"""광고 등록할 장소 찾기(docs/ads.md 8절, #769) — 이름 일부로 place_id를 찾는다. 읽기 전용.

    python -m ads.scripts.find_place "<이름 일부>" [--category 카페] [--limit 20]

place_id, 이름, 주소, status를 탭으로 나눠 출력한다. closed도 보이니 register에는 status가 open인 것만 넣는다.
places는 places.api로만 읽는다(#113). 카카오를 부르지 않는다.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from sqlalchemy.orm import Session

from places import api as places_api


def find(db: Session, query: str, *, category: str | None = None, limit: int = 20) -> list[dict]:
    """[{id, name, address, category, status}] 이름순. 커밋하지 않는다."""
    return places_api.search_own_by_name(db, query=query, category=category, limit=limit)


def format_row(row: dict) -> str:
    return "\t".join([row["id"], row["name"], row["address"] or "-", row["status"]])


def main(argv: Sequence[str] | None = None) -> int:
    from common.database import SessionLocal

    parser = argparse.ArgumentParser(description="이름 일부로 광고 등록할 place_id 찾기")
    parser.add_argument("name", help="장소 이름 일부(대소문자 무시)")
    parser.add_argument("--category", help="예: 카페, 음식점, 관광지")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        rows = find(db, args.name, category=args.category, limit=args.limit)
    if not rows:
        print("찾지 못했다", file=sys.stderr)
        return 1
    print("place_id\t이름\t주소\tstatus")
    for row in rows:
        print(format_row(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
