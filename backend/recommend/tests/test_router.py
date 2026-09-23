"""
라우터 배선 스모크 테스트(TestClient) — shortlist/tests/test_shortlist_api.py와 같은 패턴.
경로 파라미터 이름(mapId/runId/candidateId)이 authz.guard의 하드코딩 전제와 실제로
맞물리는지, response_model이 실제 흐름과 충돌하지 않는지가 이 테스트의 목적이다 — 세부
행동(필터 순서·unknown_policy 등)은 test_flows.py가 이미 커버한다.
"""

import pytest
from sqlalchemy import func

from authz.deps import get_membership_gateway
from authz.testing import FakeMembership
from common.database import get_db_session, session_scope
from maps.models import Membership as MembershipRow
from pins.models import Pin as PinRow
from pins.models import Reaction as ReactionRow


def _auth(user_id="user_1"):
    return {"session": user_id}


@pytest.fixture()
def app_client(db_session):
    from fastapi.testclient import TestClient

    from main import app

    def _override_get_db_session():
        with session_scope(db_session) as s:
            yield s

    app.dependency_overrides[get_db_session] = _override_get_db_session
    app.dependency_overrides[get_membership_gateway] = lambda: FakeMembership(
        {("map_1", "user_1"): "member", ("map_1", "user_2"): "member"}
    )

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


def _seed_ready_map(db_session):
    from maps.models import Map as MapRow

    db_session.add(MapRow(id="map_1", title="t", start_date="2026-01-01", end_date="2026-01-02", created_by="owner_1"))
    db_session.add(MembershipRow(map_id="map_1", user_id="user_1", role="member"))
    db_session.flush()

    pin = PinRow(
        id=__import__("uuid").uuid4(), map_id="map_1", category="음식점", kind="일반", origin="direct",
        place_id="seed_place",
        geom=func.ST_SetSRID(func.ST_MakePoint(129.0, 35.1), 4326),
        visibility="public", created_by="user_1",
    )
    db_session.add(pin)
    db_session.flush()
    db_session.add(ReactionRow(pin_id=pin.id, user_id="user_1", type="like"))
    db_session.commit()


def test_readiness_endpoint_returns_all_categories(app_client, db_session):
    _seed_ready_map(db_session)
    resp = app_client.get("/maps/map_1/recommend/readiness", cookies=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"음식점", "카페", "숙소", "관광지"}
    assert body["음식점"]["ready"] is True


def test_readiness_non_member_is_404(app_client, db_session):
    app_client.app.dependency_overrides[get_membership_gateway] = lambda: FakeMembership({})
    resp = app_client.get("/maps/map_1/recommend/readiness", cookies=_auth())
    assert resp.status_code == 404


def test_full_golden_path_run_to_execute_to_result_to_publish(app_client, db_session):
    _seed_ready_map(db_session)

    created = app_client.post("/maps/map_1/runs", json={"category": "음식점"}, cookies=_auth())
    assert created.status_code == 202
    run_id = created.json()["id"]
    assert created.json()["status"] == "collecting_evidence"

    evidence = app_client.get(f"/runs/{run_id}/evidence", cookies=_auth())
    assert evidence.status_code == 200

    confirm = app_client.post(f"/runs/{run_id}/regions/confirm", json={}, cookies=_auth())
    assert confirm.status_code == 200

    executed = app_client.post(f"/runs/{run_id}/execute", cookies=_auth())
    assert executed.status_code == 202
    assert executed.json()["status"] == "done"

    result = app_client.get(f"/runs/{run_id}/result", cookies=_auth())
    assert result.status_code == 200
    candidates = result.json()["candidates"]
    assert len(candidates) > 0  # DevPlaceSearchGateway가 항상 최소 몇 개는 채운다
    assert candidates[0]["permissions"]["can_publish"] is True

    candidate_id = candidates[0]["id"]
    published = app_client.post(f"/candidates/{candidate_id}/publish", cookies=_auth())
    assert published.status_code == 200
    assert published.json()["kind"] == "AI추천"


def test_other_members_cannot_operate_someone_elses_run_execution(app_client, db_session):
    """가드레일1("대안은 요청한 사람에게만 먼저 보인다") 회귀 테스트 — 루트가 Antigravity
    검수로 발견해 고친 버그. user_2도 map_1의 실제 구성원이지만(app_client 픽스처의
    FakeMembership 참고) user_1의 run 실행계(지역확인·실행·결과조회·반경넓히기·재시도)에는
    접근할 수 없어야 한다 — evidence는 협업적이라 별도 테스트(아래)로 뺐다(#32 결정)."""
    _seed_ready_map(db_session)

    created = app_client.post("/maps/map_1/runs", json={"category": "음식점"}, cookies=_auth("user_1"))
    run_id = created.json()["id"]

    for method, path in [
        ("post", f"/runs/{run_id}/regions/confirm"),
        ("post", f"/runs/{run_id}/execute"),
        ("get", f"/runs/{run_id}/result"),
        ("post", f"/runs/{run_id}/widen"),
        ("post", f"/runs/{run_id}/retry"),
    ]:
        kwargs = {"json": {}} if method in ("patch", "post") else {}
        resp = getattr(app_client, method)(path, cookies=_auth("user_2"), **kwargs)
        assert resp.status_code == 403, f"{method.upper()} {path} expected 403, got {resp.status_code}"


def test_other_members_can_view_and_add_evidence_on_someone_elses_run(app_client, db_session):
    """#32 결정(2026-09-23, 최종기획안 5-5 "근거 목록은 구성원별로 한 줄씩 따로 뜬다") 회귀
    테스트 — evidence는 run.requested_by 본인이 아니어도 지도 구성원이면 조회·추가할 수
    있어야 한다(recommend.evidence, 가드레일1과 무관 — 게시 전 비공개 후보 자체는 여전히
    본인만 보인다, 위 test_other_members_cannot_operate 참고)."""
    _seed_ready_map(db_session)

    created = app_client.post("/maps/map_1/runs", json={"category": "음식점"}, cookies=_auth("user_1"))
    run_id = created.json()["id"]

    get_resp = app_client.get(f"/runs/{run_id}/evidence", cookies=_auth("user_2"))
    assert get_resp.status_code == 200

    patch_resp = app_client.patch(
        f"/runs/{run_id}/evidence", json={"toggle": [], "add": [{"text": "user_2가 추가한 근거"}]},
        cookies=_auth("user_2"),
    )
    assert patch_resp.status_code == 200
    assert any(line["text"] == "user_2가 추가한 근거" for line in patch_resp.json())


def test_run_not_found_is_404(app_client, db_session):
    _seed_ready_map(db_session)
    resp = app_client.get(f"/runs/{'0' * 8}-0000-0000-0000-{'0' * 12}/evidence", cookies=_auth())
    assert resp.status_code == 404
