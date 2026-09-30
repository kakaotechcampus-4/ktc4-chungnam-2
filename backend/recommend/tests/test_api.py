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
