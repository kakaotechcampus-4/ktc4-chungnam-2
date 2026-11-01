"""신고된 후기 목록(docs/credits-reviews.md 5절 「숨김」, 10절, #432 D8) — 신고가 많은 순으로 보고 hide.py로 숨길지 정한다.

    python -m reviews.scripts.reports [--limit 20] [--all]

기본은 아직 숨기지 않은 후기만 보인다(할 일 목록). --all이면 숨긴 후기도 [숨김] 표시와 함께 보인다. 읽기 전용이다.
신고 수가 같으면 마지막 신고가 최근인 것이 먼저다. 장소 이름은 places.api로 읽는다(#113).
작성자와 신고자는 출력하지 않는다 — 숨길지는 글로 정한다. 후기 글은 이 터미널에만 나오고 로그·모델로 가지 않는다.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from places import api as places_api
from reviews.models import Review, ReviewReport


@dataclass(frozen=True)
class ReportedReview:
    review_id: str
    place_id: str
    place_name: str | None
    report_count: int
    last_reported_at: datetime
    rating: int
    body: str
    hidden: bool


def reported_reviews(db: Session, *, limit: int = 20, include_hidden: bool = False) -> list[ReportedReview]:
    """신고가 한 번이라도 있는 후기를 신고 수 많은 순으로. 커밋하지 않는다."""
    count = func.count().label("report_count")
    last = func.max(ReviewReport.created_at).label("last_reported_at")
    query = (
        select(Review.id, Review.place_id, Review.rating, Review.body, Review.hidden_at, count, last)
        .join(ReviewReport, ReviewReport.review_id == Review.id)
        .group_by(Review.id)
        .order_by(count.desc(), last.desc(), Review.id)
        .limit(limit)
    )
    if not include_hidden:
        query = query.where(Review.hidden_at.is_(None))
    rows = db.execute(query).all()
    names = places_api.get_places(list({r.place_id for r in rows}), db=db) if rows else {}
    return [
        ReportedReview(
            review_id=str(r.id), place_id=r.place_id, place_name=names[r.place_id].name if r.place_id in names else None,
            report_count=r.report_count, last_reported_at=r.last_reported_at, rating=r.rating, body=r.body,
            hidden=r.hidden_at is not None,
        )
        for r in rows
    ]


def format_report(item: ReportedReview) -> str:
    head = f"{item.review_id}  신고 {item.report_count}회  마지막 {item.last_reported_at:%Y-%m-%d %H:%M}"
    if item.hidden:
        head += "  [숨김]"
    place = item.place_name or "(이름 없음)"
    return f"{head}\n  장소 {place} ({item.place_id})  별점 {item.rating}\n  {item.body}"


def main(argv: Sequence[str] | None = None) -> int:
    from common.database import SessionLocal

    parser = argparse.ArgumentParser(description="신고된 후기 목록(신고 많은 순)")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--all", action="store_true", help="숨긴 후기도 보인다")
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        items = reported_reviews(db, limit=args.limit, include_hidden=args.all)
    if not items:
        print("신고된 후기가 없다")
        return 0
    print("\n\n".join(format_report(item) for item in items))
    return 0


if __name__ == "__main__":
    sys.exit(main())
