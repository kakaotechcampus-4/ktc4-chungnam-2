"""api.reassign_user(게스트 합치기, #694) — 게스트의 agent 기록을 카카오 계정으로 옮기고, 겹치면 카카오 쪽이 이긴다.
열람은 같은 제안을 둘 다 봤을 때, 코스 요청은 같은 지도에 둘 다 진행 중일 때 게스트 것을 지운다. 다른 사용자 행은 그대로다."""

import uuid
from datetime import timedelta

from sqlalchemy import select

from agent import api
from agent.course.models import AgentCourseRun
from agent.models import AgentSettings, AgentSuggestion, AgentSuggestionView
from agent.tests import rows

GUEST, KAKAO, OTHER = "guest", "kakao", "other"
ZERO = {
    "agent_suggestion_views": 0, "agent_suggestion_views_dropped": 0, "agent_settings": 0, "agent_suggestions": 0,
    "agent_course_runs": 0, "agent_course_runs_dropped": 0,
}


def view_at(db, suggestion_id, user_id, minutes):
    return rows.add(db, AgentSuggestionView(
        suggestion_id=suggestion_id, user_id=user_id, viewed_at=rows.NOW + timedelta(minutes=minutes),
    ))


def course_run(db, map_id, requested_by, status):
    return rows.add(db, AgentCourseRun(
        id=uuid.uuid4(), map_id=map_id, requested_by=requested_by, status=status,
        input={"request_text": "", "member_constraints": []}, snapshot_at=rows.NOW, snapshot_pin_ids=[],
    ))


def views(db):
    return sorted(db.execute(select(AgentSuggestionView.suggestion_id, AgentSuggestionView.user_id,
                                    AgentSuggestionView.viewed_at)).all())


def course_runs(db):
    return {r.id: (r.map_id, r.requested_by, r.status) for r in db.execute(select(AgentCourseRun)).scalars()}


# ---------------------------------------------------------------- 열람

def test_view_of_same_suggestion_keeps_kakao_one_and_moves_the_rest(db_session):
    both = rows.suggestion(db_session, "m1")
    guest_only = rows.suggestion(db_session, "m2")
    view_at(db_session, both.id, GUEST, 1)
    view_at(db_session, both.id, KAKAO, 5)
    view_at(db_session, guest_only.id, GUEST, 2)
    view_at(db_session, both.id, OTHER, 3)

    result = api.reassign_user(db_session, from_user_id=GUEST, to_user_id=KAKAO)

    assert result["agent_suggestion_views"] == 1 and result["agent_suggestion_views_dropped"] == 1
    db_session.expire_all()
    assert views(db_session) == sorted([
        (both.id, KAKAO, rows.NOW + timedelta(minutes=5)),       # 카카오 쪽 열람 시각이 남는다
        (guest_only.id, KAKAO, rows.NOW + timedelta(minutes=2)),
        (both.id, OTHER, rows.NOW + timedelta(minutes=3)),
    ])


# ---------------------------------------------------------------- 코스 요청

def test_active_course_runs_on_same_map_keep_kakao_one(db_session):
    clash_guest = course_run(db_session, "m1", GUEST, "running")
    clash_kakao = course_run(db_session, "m1", KAKAO, "queued")
    old_guest = course_run(db_session, "m1", GUEST, "done")            # 끝난 run은 겹쳐도 옮긴다
    alone_guest = course_run(db_session, "m2", GUEST, "queued")        # 카카오의 진행 중 run이 없는 지도
    finished_kakao = course_run(db_session, "m3", KAKAO, "done")
    active_guest_m3 = course_run(db_session, "m3", GUEST, "running")   # 카카오 쪽은 끝났으니 겹치지 않는다
    other_m1 = course_run(db_session, "m1", OTHER, "running")

    result = api.reassign_user(db_session, from_user_id=GUEST, to_user_id=KAKAO)

    assert result["agent_course_runs"] == 3 and result["agent_course_runs_dropped"] == 1
    db_session.expire_all()
    assert course_runs(db_session) == {
        clash_kakao.id: ("m1", KAKAO, "queued"),
        old_guest.id: ("m1", KAKAO, "done"),
        alone_guest.id: ("m2", KAKAO, "queued"),
        finished_kakao.id: ("m3", KAKAO, "done"),
        active_guest_m3.id: ("m3", KAKAO, "running"),
        other_m1.id: ("m1", OTHER, "running"),
    }
    assert clash_guest.id not in course_runs(db_session)


# ---------------------------------------------------------------- 그대로 바꾸는 칸

def test_settings_and_resolved_by_are_rewritten(db_session):
    rows.add(db_session, AgentSettings(map_id="m1", enabled=False, updated_by=GUEST))
    rows.add(db_session, AgentSettings(map_id="m2", enabled=True, updated_by=OTHER))
    mine = rows.suggestion(db_session, "m1", status="dismissed", resolved_by=GUEST)
    theirs = rows.suggestion(db_session, "m1", status="accepted", resolved_by=OTHER)
    open_ = rows.suggestion(db_session, "m2")

    result = api.reassign_user(db_session, from_user_id=GUEST, to_user_id=KAKAO)

    assert result["agent_settings"] == 1 and result["agent_suggestions"] == 1
    db_session.expire_all()
    assert dict(db_session.execute(select(AgentSettings.map_id, AgentSettings.updated_by)).all()) == {
        "m1": KAKAO, "m2": OTHER,
    }
    assert db_session.get(AgentSuggestion, mine.id).resolved_by == KAKAO
    assert db_session.get(AgentSuggestion, theirs.id).resolved_by == OTHER
    assert db_session.get(AgentSuggestion, open_.id).resolved_by is None


# ---------------------------------------------------------------- 멱등, 같은 id

def _seed_everything(db):
    s = rows.suggestion(db, "m1", status="dismissed", resolved_by=GUEST)
    view_at(db, s.id, GUEST, 1)
    view_at(db, s.id, KAKAO, 2)
    view_at(db, s.id, OTHER, 3)
    rows.add(db, AgentSettings(map_id="m1", enabled=False, updated_by=GUEST))
    course_run(db, "m1", GUEST, "running")
    course_run(db, "m1", KAKAO, "running")
    course_run(db, "m2", GUEST, "done")
    course_run(db, "m1", OTHER, "queued")


def test_second_call_changes_nothing(db_session):
    _seed_everything(db_session)
    first = api.reassign_user(db_session, from_user_id=GUEST, to_user_id=KAKAO)
    db_session.expire_all()
    after_first = (views(db_session), course_runs(db_session))

    second = api.reassign_user(db_session, from_user_id=GUEST, to_user_id=KAKAO)

    assert first == {
        "agent_suggestion_views": 0, "agent_suggestion_views_dropped": 1, "agent_settings": 1, "agent_suggestions": 1,
        "agent_course_runs": 1, "agent_course_runs_dropped": 1,
    }
    assert second == ZERO
    db_session.expire_all()
    assert (views(db_session), course_runs(db_session)) == after_first


def test_same_id_does_nothing(db_session):
    _seed_everything(db_session)
    db_session.expire_all()
    before = (views(db_session), course_runs(db_session))

    assert api.reassign_user(db_session, from_user_id=GUEST, to_user_id=GUEST) == ZERO

    db_session.expire_all()
    assert (views(db_session), course_runs(db_session)) == before


def test_other_users_rows_stay(db_session):
    _seed_everything(db_session)

    api.reassign_user(db_session, from_user_id=GUEST, to_user_id=KAKAO)

    db_session.expire_all()
    assert [v.user_id for v in views(db_session)].count(OTHER) == 1
    assert [r for r in course_runs(db_session).values() if r[1] == OTHER] == [("m1", OTHER, "queued")]
    assert GUEST not in {v.user_id for v in views(db_session)}
    assert GUEST not in {r[1] for r in course_runs(db_session).values()}
