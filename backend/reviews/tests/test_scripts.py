"""관리 스크립트(docs/credits-reviews.md 5절 「숨김」, #432 D8) — 신고 많은 순 목록과 숨기기·되돌리기."""

import uuid

from reviews.models import Review, ReviewReport
from reviews.scripts import hide, reports


def _report(world, review_id: str, *reporters: str) -> None:
    for name in reporters:
        world.db.add(ReviewReport(review_id=uuid.UUID(review_id), reporter_id=world.uid(name)))
    world.db.flush()


def test_reported_reviews_are_ordered_by_report_count(world):
    place_id = world.place("성수 칼국수")
    few = world.review(place_id, world.uid("a"), body="조금 신고된 글")
    many = world.review(place_id, world.uid("b"), rating=1, body="많이 신고된 글")
    world.review(place_id, world.uid("c"), body="신고 없는 글")
    _report(world, few, "x")
    _report(world, many, "x", "y", "z")

    items = reports.reported_reviews(world.db)

    mine = [i for i in items if i.review_id in (few, many)]
    assert [(i.review_id, i.report_count) for i in mine] == [(many, 3), (few, 1)]
    assert mine[0].place_name == "성수 칼국수" and mine[0].rating == 1 and mine[0].body == "많이 신고된 글"
    text = reports.format_report(mine[0])
    assert many in text and "신고 3회" in text and world.uid("x") not in text and world.uid("b") not in text


def test_hidden_reviews_show_only_with_all(world):
    review_id = world.review(world.place(), world.uid("a"))
    _report(world, review_id, "x")
    hide.set_hidden(world.db, review_id, hidden=True)

    assert review_id not in {i.review_id for i in reports.reported_reviews(world.db)}
    [item] = [i for i in reports.reported_reviews(world.db, include_hidden=True) if i.review_id == review_id]
    assert item.hidden and "[숨김]" in reports.format_report(item)


def test_hide_and_undo(world):
    review_id = world.review(world.place(), world.uid("a"))
    row = world.db.get(Review, uuid.UUID(review_id))

    assert hide.set_hidden(world.db, review_id, hidden=True) is True
    assert row.hidden_at is not None
    assert hide.set_hidden(world.db, review_id, hidden=True) is False
    assert hide.set_hidden(world.db, review_id, hidden=False) is True
    assert row.hidden_at is None
    assert hide.set_hidden(world.db, review_id, hidden=False) is False


def test_hide_unknown_review_is_none(world):
    assert hide.set_hidden(world.db, str(uuid.uuid4()), hidden=True) is None
    assert hide.set_hidden(world.db, "not-a-uuid", hidden=True) is None
