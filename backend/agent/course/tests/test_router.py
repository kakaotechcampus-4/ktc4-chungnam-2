"""AI 코스 짜기 엔드포인트 3개 — 실제 앱, 실제 멤버십, 실제 DB로 HTTP를 두드린다. 모델은 스텁이다.

TestClient는 응답 뒤의 BackgroundTasks까지 끝내고 돌아오므로, POST 직후 GET이 완료된 run을 본다(통합 흐름).
"""

import uuid
from datetime import timedelta

from fastapi.testclient import TestClient

from agent.course.constants import COURSE_DAILY_LIMIT
from agent.course.gateways import CourseLlm
from agent.course.models import AgentCourseRun
from agent.course.tests.conftest import confirmed_map
from agent.course.tests.test_runner import TEXT, direct_planner, goals_planner
from auth.testing import ensure_users


def outsider(world, name="x"):
    with world.factory() as db:
        ensure_users(db, world.uid(name))
        db.commit()
    world.user_ids.add(world.uid(name))


def insert_run(world, map_id, *, user="u1", status="done", created_at=None):
    with world.factory() as db:
        r = AgentCourseRun(map_id=map_id, requested_by=world.uid(user), status=status, input={}, snapshot_at=world.now,
                           snapshot_pin_ids=[], created_at=created_at or world.now)
        db.add(r)
        db.commit()
        return str(r.id)


# ---------------------------------------------------------------- 진행 중 GET

def _running_ids(world):
    with world.factory() as db:
        return [str(r.id) for r in db.query(AgentCourseRun).filter(AgentCourseRun.status == "running")]


def test_get_while_running_returns_the_steps_so_far(world, places, client):
    map_id, _ = confirmed_map(world, places, 4)
    u1, watcher = client("u1"), client("u1")
    seen: list[dict] = []
    queue = direct_planner()

    def inspecting(i):                # 모델 턴 한가운데에서 다른 연결로 GET — 계산은 아직 안 끝났다
        (rid,) = _running_ids(world)
        seen.append(watcher.get(f"/course-runs/{rid}").json())
        return queue(i)

    client.set_llm(CourseLlm(goals_planner, inspecting))
    res = u1.post(f"/maps/{map_id}/courses", json={"request_text": TEXT, "member_constraints": []})
    assert res.status_code == 202

    first, second = seen
    for body in seen:
        assert body["status"] == "running" and body["outcome"] is None and body["finished_at"] is None
        assert body["days"] == [] and body["violations"] == [] and body["checks"] == []     # 결과 칸은 비어 있다
    assert [s["stage"] for s in first["steps"]][:2] == ["이해", "확인"]
    assert len(second["steps"]) > len(first["steps"])
    assert second["steps"][: len(first["steps"])] == first["steps"]                          # 앞 단계는 그대로, 뒤로만 늘어난다
    assert {"stage", "role", "by", "by_detail", "text"} == set(first["steps"][0])
    done = u1.get(f"/course-runs/{res.json()['course_run_id']}").json()
    assert done["status"] == "done" and done["steps"][: len(second["steps"])] == second["steps"]


# ---------------------------------------------------------------- 통합: 요청 → 백그라운드 → 완료

def test_request_runs_in_background_and_get_returns_done(world, places, client):
    map_id, pin_ids = confirmed_map(world, places, 4, live=1)
    client.set_llm(CourseLlm(goals_planner, direct_planner()))
    u1 = client("u1")

    res = u1.post(f"/maps/{map_id}/courses", json={"request_text": TEXT, "member_constraints": []})

    assert res.status_code == 202
    run_id = res.json()["course_run_id"]
    body = u1.get(f"/course-runs/{run_id}").json()
    assert body["id"] == run_id and body["map_id"] == map_id
    assert body["status"] == "done" and body["outcome"] == "solved_with_checks" and body["failure_code"] is None
    goal = body["goals"][0]                      # 요일은 지도 날짜에 따라 달라진다(world는 오늘 + 30일)
    assert len(body["goals"]) == 1 and (goal["id"], goal["kind"], goal["met"]) == ("day_indoor:d2", "day_indoor", True)
    assert goal["label"].startswith("둘째 날 (") and goal["label"].endswith(")은 실내 위주로")
    assert body["unmatched"] == ["웨이팅 없는 곳으로"]
    step = body["steps"][0]
    assert (step["stage"], step["role"], step["by"], step["by_detail"]) == ("이해", "해석", "ai", None) and step["text"].endswith("「웨이팅 없는 곳으로」는 그대로는 판단할 수 없어요")
    assert sorted(s["pin_id"] for d in body["days"] for s in d["slots"]) == sorted(pin_ids[:4])
    assert [e["pin_id"] for e in body["excluded"]] == [pin_ids[4]] and body["excluded"][0]["reason"] == "NO_COORDINATES"
    assert len(body["checks"]) == 4 and body["violations"] == [] and body["stale"] is False
    assert body["finished_at"] is not None and body["snapshot_at"] and body["created_at"]
    assert {"date", "slots", "legs"} <= set(body["days"][0])


def test_request_without_body_or_model_still_makes_a_baseline_course(world, places, client):
    map_id, _ = confirmed_map(world, places, 3)
    u1 = client("u1")

    res = u1.post(f"/maps/{map_id}/courses")

    assert res.status_code == 202
    body = u1.get(f"/course-runs/{res.json()['course_run_id']}").json()
    assert body["status"] == "done" and body["goals"] == [] and body["unmatched"] == []


def test_unmatched_request_without_model(world, places, client):
    map_id, _ = confirmed_map(world, places, 3)
    u1 = client("u1")
    run_id = u1.post(f"/maps/{map_id}/courses", json={"request_text": TEXT}).json()["course_run_id"]
    assert u1.get(f"/course-runs/{run_id}").json()["unmatched"] == [TEXT]


# ---------------------------------------------------------------- 권한

def test_non_member_gets_404_everywhere(world, places, client):
    map_id, _ = confirmed_map(world, places, 3)
    run_id = insert_run(world, map_id)
    outsider(world)
    x = client("x")

    assert x.post(f"/maps/{map_id}/courses").status_code == 404
    assert x.get(f"/maps/{map_id}/courses/latest").status_code == 404
    assert x.get(f"/course-runs/{run_id}").status_code == 404


def test_member_who_did_not_request_gets_403_and_latest_is_only_mine(world, places, client):
    map_id, _ = confirmed_map(world, places, 3)
    run_id = insert_run(world, map_id, user="u1")
    u2 = client("u2")

    assert u2.get(f"/course-runs/{run_id}").status_code == 403
    assert u2.get(f"/maps/{map_id}/courses/latest").status_code == 204        # 남의 run은 내 마지막이 아니다
    assert u2.get(f"/course-runs/{uuid.uuid4()}").status_code == 404
    assert u2.get("/course-runs/not-a-uuid").status_code == 404


def test_unauthenticated_is_401(world, places, client):
    from main import app
    map_id, _ = confirmed_map(world, places, 3)
    assert TestClient(app).post(f"/maps/{map_id}/courses").status_code == 401


# ---------------------------------------------------------------- 에러

def test_not_enough_places_is_422(world, places, client):
    map_id, _ = confirmed_map(world, places, 1, live=2)
    res = client("u1").post(f"/maps/{map_id}/courses")
    assert res.status_code == 422
    assert res.json() == {"code": "COURSE_NOT_ENOUGH_PLACES", "message": "코스를 짤 확정 장소가 부족합니다",
                          "detail": {"min": 2, "count": 1}}


def test_in_progress_is_409_with_run_id(world, places, client):
    map_id, _ = confirmed_map(world, places, 3)
    running = insert_run(world, map_id, status="running")
    res = client("u1").post(f"/maps/{map_id}/courses")
    assert res.status_code == 409 and res.json()["code"] == "COURSE_IN_PROGRESS"
    assert res.json()["detail"] == {"course_run_id": running}


def test_daily_limit_is_429_after_five_runs(world, places, client):
    map_id, _ = confirmed_map(world, places, 3)
    u1 = client("u1")
    for _ in range(COURSE_DAILY_LIMIT):
        assert u1.post(f"/maps/{map_id}/courses").status_code == 202        # 매번 끝까지 돌아 다음 요청이 막히지 않는다

    res = u1.post(f"/maps/{map_id}/courses")

    assert res.status_code == 429 and res.json()["code"] == "COURSE_LIMIT"
    assert res.json()["detail"] == {"limit": 5, "used": 5}
    assert client("u2").post(f"/maps/{map_id}/courses").status_code == 202


def test_request_body_validation_is_422(world, places, client):
    map_id, _ = confirmed_map(world, places, 3)
    u1 = client("u1")
    for body in ({"request_text": "가" * 101}, {"member_constraints": [{"kind": "daily_walk_max", "value": 5}]},
                 {"member_constraints": [{"kind": "other", "value": 60}]}):
        res = u1.post(f"/maps/{map_id}/courses", json=body)
        assert res.status_code == 422 and res.json()["code"] == "VALIDATION_ERROR"
    res = u1.post(f"/maps/{map_id}/courses", json={"member_constraints": [{"kind": "daily_walk_max", "value": 60, "day": "d9"}]})
    assert res.status_code == 422 and res.json()["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------- latest, stale

def test_latest_is_204_then_returns_my_newest_run(world, places, client):
    map_id, _ = confirmed_map(world, places, 3)
    u1 = client("u1")
    assert u1.get(f"/maps/{map_id}/courses/latest").status_code == 204

    first = u1.post(f"/maps/{map_id}/courses").json()["course_run_id"]
    second = u1.post(f"/maps/{map_id}/courses", json={"request_text": TEXT}).json()["course_run_id"]

    latest = u1.get(f"/maps/{map_id}/courses/latest")
    assert latest.status_code == 200 and latest.json()["id"] == second != first


def test_latest_shows_a_run_that_is_still_running(world, places, client):
    map_id, _ = confirmed_map(world, places, 3)
    run_id = insert_run(world, map_id, status="running")
    body = client("u1").get(f"/maps/{map_id}/courses/latest").json()
    assert body["id"] == run_id and body["status"] == "running" and body["outcome"] is None
    assert body["days"] == [] and body["steps"] == [] and body["finished_at"] is None


def test_stale_when_the_confirmed_list_changed_after_the_run(world, places, client):
    map_id, pin_ids = confirmed_map(world, places, 3)
    u1 = client("u1")
    run_id = u1.post(f"/maps/{map_id}/courses").json()["course_run_id"]
    assert u1.get(f"/course-runs/{run_id}").json()["stale"] is False

    extra = world.pin(map_id, place_id="place_new")
    places.add("place_new", "새곳", 37.58, 126.99)
    world.confirm(map_id, extra)

    assert u1.get(f"/course-runs/{run_id}").json()["stale"] is True


# ---------------------------------------------------------------- 오래된 진행 중 run은 조회에서도 끝난다 (#736)

def _db_row(world, run_id):
    with world.factory() as db:
        r = db.get(AgentCourseRun, uuid.UUID(run_id))
        return r.status, r.failure_code, r.finished_at


def _minutes_ago(world, minutes):
    return world.now - timedelta(minutes=minutes)


def test_get_fails_a_running_run_older_than_stale_after(world, places, client):
    map_id, _ = confirmed_map(world, places, 3)
    run_id = insert_run(world, map_id, status="running", created_at=_minutes_ago(world, 16))

    body = client("u1").get(f"/course-runs/{run_id}").json()

    assert (body["status"], body["failure_code"]) == ("failed", "INTERRUPTED") and body["finished_at"] is not None
    status, code, finished = _db_row(world, run_id)
    assert (status, code) == ("failed", "INTERRUPTED") and finished is not None


def test_latest_fails_a_running_run_older_than_stale_after(world, places, client):
    map_id, _ = confirmed_map(world, places, 3)
    run_id = insert_run(world, map_id, status="queued", created_at=_minutes_ago(world, 16))

    body = client("u1").get(f"/maps/{map_id}/courses/latest").json()

    assert body["id"] == run_id and (body["status"], body["failure_code"]) == ("failed", "INTERRUPTED")
    assert body["finished_at"] is not None
    assert _db_row(world, run_id)[:2] == ("failed", "INTERRUPTED")


def test_get_keeps_a_running_run_within_stale_after(world, places, client):
    map_id, _ = confirmed_map(world, places, 3)
    run_id = insert_run(world, map_id, status="running", created_at=_minutes_ago(world, 14))
    u1 = client("u1")

    assert u1.get(f"/course-runs/{run_id}").json()["status"] == "running"
    assert u1.get(f"/maps/{map_id}/courses/latest").json()["status"] == "running"
    assert _db_row(world, run_id) == ("running", None, None)


def test_get_leaves_finished_runs_alone(world, places, client):
    map_id, _ = confirmed_map(world, places, 3)
    done_id = insert_run(world, map_id, status="done", created_at=_minutes_ago(world, 60))
    failed_id = insert_run(world, map_id, status="failed", created_at=_minutes_ago(world, 30))
    with world.factory() as db:
        db.get(AgentCourseRun, uuid.UUID(failed_id)).failure_code = "ENGINE_ERROR"
        db.commit()
    u1 = client("u1")

    assert u1.get(f"/course-runs/{done_id}").json()["status"] == "done"
    assert u1.get(f"/course-runs/{failed_id}").json()["failure_code"] == "ENGINE_ERROR"
    assert _db_row(world, done_id) == ("done", None, None)
    assert _db_row(world, failed_id)[:2] == ("failed", "ENGINE_ERROR")
