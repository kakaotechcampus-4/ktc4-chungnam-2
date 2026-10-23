"""api.reassign_user(#560) — 게스트의 run 요청자·근거 줄 작성자·제외 요청자를 옮긴다. 충돌은 to_user 것이 이긴다."""

from recommend import api
from recommend.models import EvidenceLine, Exclusion, RecommendRun


def _run(db, map_id, requested_by, attempt_no=1):
    run = RecommendRun(map_id=map_id, category="음식점", requested_by=requested_by, status="done", attempt_no=attempt_no)
    db.add(run)
    db.flush()
    return run


def _line(db, run, author):
    db.add(EvidenceLine(run_id=run.id, author_id=author, source="manual", text="매운 곳", badge="required"))


def _exclusion(db, run, requested_by, place_id="p1", reason="dismissed"):
    db.add(Exclusion(map_id=run.map_id, category="음식점", place_id=place_id, reason=reason, run_id=run.id,
                     requested_by=requested_by))
    db.flush()


def test_moves_runs_lines_and_exclusions_keeping_attempt_no(db_session):
    run = _run(db_session, "m1", "guest", attempt_no=4)
    _line(db_session, run, "guest")
    _exclusion(db_session, run, "guest")

    result = api.reassign_user(db_session, from_user_id="guest", to_user_id="kakao")

    assert result == {"recommend_runs": 1, "evidence_lines": 1, "exclusions": 1}
    assert [(r.requested_by, r.attempt_no) for r in db_session.query(RecommendRun)] == [("kakao", 4)]
    assert [l.author_id for l in db_session.query(EvidenceLine)] == ["kakao"]
    assert [e.requested_by for e in db_session.query(Exclusion)] == ["kakao"]


def test_overlapping_exclusion_keeps_the_kakao_row(db_session):
    run = _run(db_session, "m1", "guest")
    _exclusion(db_session, run, "kakao", place_id="p1", reason="proposed")
    _exclusion(db_session, run, "guest", place_id="p1", reason="dismissed")   # 같은 (지도, 장소) → 지운다
    _exclusion(db_session, run, "guest", place_id="p2")                        # 겹치지 않음 → 옮긴다
    _exclusion(db_session, _run(db_session, "m2", "guest"), "guest", place_id="p1")   # 다른 지도의 같은 장소 → 옮긴다

    result = api.reassign_user(db_session, from_user_id="guest", to_user_id="kakao")

    assert result["exclusions"] == 2
    rows = sorted((e.map_id, e.place_id, e.requested_by, e.reason) for e in db_session.query(Exclusion))
    assert rows == [("m1", "p1", "kakao", "proposed"), ("m1", "p2", "kakao", "dismissed"),
                    ("m2", "p1", "kakao", "dismissed")]


def test_idempotent(db_session):
    run = _run(db_session, "m1", "guest")
    _line(db_session, run, "guest")
    _exclusion(db_session, run, "guest")
    api.reassign_user(db_session, from_user_id="guest", to_user_id="kakao")

    assert api.reassign_user(db_session, from_user_id="guest", to_user_id="kakao") == {
        "recommend_runs": 0, "evidence_lines": 0, "exclusions": 0,
    }


def test_same_id_does_nothing(db_session):
    run = _run(db_session, "m1", "u1")
    _exclusion(db_session, run, "u1")

    assert set(api.reassign_user(db_session, from_user_id="u1", to_user_id="u1").values()) == {0}
    assert db_session.query(Exclusion).count() == 1


def test_other_users_rows_unchanged(db_session):
    run = _run(db_session, "m1", "someone")
    _line(db_session, run, "someone")
    _exclusion(db_session, run, "someone")

    assert set(api.reassign_user(db_session, from_user_id="guest", to_user_id="kakao").values()) == {0}
    assert [r.requested_by for r in db_session.query(RecommendRun)] == ["someone"]
    assert [l.author_id for l in db_session.query(EvidenceLine)] == ["someone"]
    assert [e.requested_by for e in db_session.query(Exclusion)] == ["someone"]
