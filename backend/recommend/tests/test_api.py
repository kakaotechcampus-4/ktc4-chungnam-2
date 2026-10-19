"""recommend.api 공개 함수 — 다른 모듈(탈퇴 등)이 부르는 경로."""

import uuid

from sqlalchemy import func, select

from recommend import api
from recommend.models import EvidenceLine, RecommendRun


def _run(db_session):
    run = RecommendRun(id=uuid.uuid4(), map_id="map_1", category="음식점", requested_by="user_1", status="done")
    db_session.add(run)
    db_session.flush()
    return run


def _line(db_session, run, author_id):
    db_session.add(EvidenceLine(run_id=run.id, author_id=author_id, source="manual", text="t", badge="preferred"))
    db_session.flush()


def test_delete_evidence_lines_by_author_removes_only_that_users_lines_across_runs(db_session):
    run_a, run_b = _run(db_session), _run(db_session)
    _line(db_session, run_a, "leaver")
    _line(db_session, run_b, "leaver")
    _line(db_session, run_b, "stayer")

    deleted = api.delete_evidence_lines_by_author(db_session, user_id="leaver")

    assert deleted == 2
    remaining = db_session.execute(select(EvidenceLine.author_id)).scalars().all()
    assert remaining == ["stayer"]


def test_delete_evidence_lines_by_author_returns_zero_when_none(db_session):
    assert api.delete_evidence_lines_by_author(db_session, user_id="nobody") == 0
    assert db_session.execute(select(func.count()).select_from(EvidenceLine)).scalar_one() == 0


# ---------- fact_labels, demote_wanted_place_identity (#564, agent가 부른다) ----------


def test_fact_labels_returns_a_copy_of_the_display_names():
    from recommend import constraints

    labels = api.fact_labels()
    assert labels == constraints.FACT_LABELS
    assert labels["quiet"] == "조용한 곳"
    labels["quiet"] = "바뀜"
    assert constraints.FACT_LABELS["quiet"] == "조용한 곳"


def test_demote_wanted_place_identity_lowers_wanted_cuisine_only():
    lines = [
        {"fact_key": "cuisine_bbq", "wants": True, "badge": "required"},
        {"fact_key": "cuisine_bbq", "wants": False, "badge": "required"},
        {"fact_key": "quiet", "wants": True, "badge": "required"},
    ]

    result = api.demote_wanted_place_identity("음식점", lines)

    assert [line["badge"] for line in result] == ["preferred", "required", "required"]
    assert lines[0]["badge"] == "required"  # 원본은 그대로


def test_demote_wanted_place_identity_lowers_wanted_chips_but_not_accessibility():
    """#617 — agent 요약도 같은 함수를 쓴다: 「좁아요」는 preferred(must_keep으로 가지 않는다), 접근성·피함 칩은 required."""
    lines = [
        {"fact_key": "spacious", "wants": True, "badge": "required", "chip_id": "food_cramped"},
        {"fact_key": "spicy_focused", "wants": False, "badge": "required", "chip_id": "food_spicy"},
        {"fact_key": "parking_available", "wants": True, "badge": "required"},
    ]
    assert [l["badge"] for l in api.demote_wanted_place_identity("음식점", lines)] == ["preferred", "required", "required"]

    accessible = [{"fact_key": "accessible", "wants": True, "badge": "required", "chip_id": "sight_inaccessible"}]
    assert api.demote_wanted_place_identity("관광지", accessible) == accessible


def test_demote_wanted_place_identity_leaves_other_categories_alone():
    lines = [{"fact_key": "cuisine_bbq", "wants": True, "badge": "required"}]
    assert api.demote_wanted_place_identity("카페", lines) == lines
