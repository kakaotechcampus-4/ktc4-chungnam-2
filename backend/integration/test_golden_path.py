"""
골든 패스 — 프론트가 하게 될 요청 흐름을 모듈 경계를 넘어 끝까지 한 번에 돌린다.

모듈 단위 테스트는 각자 이웃 모듈을 가짜(FakeMembership 등)로 바꿔 끼우므로, 모듈 사이의 이음새
(지도 생성이 만든 멤버십으로 핀 인가 통과, 추천 게시 핀에 checks 유지, confirmed_count 집계 …)는
여기서만 검증된다. 2026-09-29 실서버 스모크(40단계)를 pytest로 옮긴 것이다.

SSE는 TestClient가 스트림을 끊지 못해 여기서 다루지 않는다(realtime 모듈 테스트 소관).
"""

import pytest

from main import app  # noqa: F401  — 라우터 등록을 보장

REGION = {"label": "부산", "lat": 35.1796, "lng": 129.0756}


def _pin(client, map_id, cat, lat, lng, place_id, name=None):
    body = {"category": cat, "source": "coordinate", "lat": lat, "lng": lng, "place_id": place_id}
    if name:
        body["place_name"] = name
    return client.post(f"/maps/{map_id}/pins", json=body)


@pytest.fixture()
def clients(app_client, two_users):
    """같은 앱에 쿠키만 다른 두 클라이언트(a=지도 만든 사람, b=초대받는 사람)."""
    from fastapi.testclient import TestClient

    a = TestClient(app_client.app, cookies={"session": "user_a"})
    b = TestClient(app_client.app, cookies={"session": "user_b"})
    anon = TestClient(app_client.app)
    yield a, b, anon
    for c in (a, b, anon):
        c.close()


def test_unauthenticated_request_is_401(clients):
    _, _, anon = clients
    r = anon.get("/maps")
    assert r.status_code == 401
    assert r.json()["code"] == "UNAUTHORIZED"


def test_map_invite_pins_reactions_recommend_publish_shortlist_route(clients):
    a, b, _ = clients

    # 지도 생성(region 왕복) · 목록 · 비구성원 격리
    r = a.post("/maps", json={"title": "부산 여행", "start_date": "2026-11-01",
                              "end_date": "2026-11-03", "region": REGION})
    assert r.status_code == 201, r.text
    map_id = r.json()["id"]
    assert r.json()["region"]["label"] == "부산"
    assert [m["id"] for m in a.get("/maps").json()] == [map_id]
    assert b.get("/maps").json() == []
    assert b.get(f"/maps/{map_id}").status_code == 404

    # 초대 → 수락 → 구성원 2명(display_name 포함)
    inv = a.post(f"/maps/{map_id}/invite")
    assert inv.status_code == 201, inv.text
    assert "/invites/" in inv.json()["url"]
    assert b.post(f"/invites/{inv.json()['token']}/accept").status_code == 200
    members = a.get(f"/maps/{map_id}/members").json()
    assert len(members) == 2 and all("display_name" in m for m in members)

    # 핀 3개 + 중복 409 + 링크만(좌표 없음)은 422
    pin_ids = []
    for i, (cat, lat, lng, name) in enumerate(
        [("음식점", 35.10, 129.03, "밀면집"), ("음식점", 35.16, 129.16, "횟집"), ("카페", 35.15, 129.12, "카페A")]
    ):
        r = _pin(a, map_id, cat, lat, lng, f"pl{i}", name)
        assert r.status_code == 201, r.text
        pin_ids.append(r.json()["id"])
    dup = _pin(a, map_id, "음식점", 35.1, 129.0, "pl0")
    assert dup.status_code == 409 and dup.json()["code"] == "PIN_DUPLICATE"
    pins = a.get(f"/maps/{map_id}/pins").json()
    assert len(pins) == 3
    assert all(p["place_name"] and p["created_by_display_name"] and "permissions" in p for p in pins)

    # 반응 — 반대는 사유가 있어야 한다(가드레일 3)
    assert a.put(f"/pins/{pin_ids[0]}/reaction", json={"type": "like"}).status_code == 200
    r = a.put(f"/pins/{pin_ids[1]}/reaction", json={"type": "against"})
    assert r.status_code == 422 and r.json()["code"] == "EVIDENCE_REQUIRED"
    assert a.put(f"/pins/{pin_ids[1]}/reaction",
                 json={"type": "against", "reason_text": "매워요"}).status_code == 200
    b.put(f"/pins/{pin_ids[0]}/reaction", json={"type": "like"})
    b.put(f"/pins/{pin_ids[1]}/reaction", json={"type": "against", "reason_text": "비싸요"})

    # 추천 — 스텁 위에서 끝까지. 결과는 요청자에게만 보인다(가드레일 1)
    assert a.get(f"/maps/{map_id}/recommend/readiness").json()["음식점"]["ready"] is True
    r = a.post(f"/maps/{map_id}/runs", json={"category": "음식점"})
    assert r.status_code == 202, r.text
    run_id = r.json()["id"]
    assert len(a.get(f"/runs/{run_id}/evidence").json()) >= 2
    assert b.get(f"/runs/{run_id}/evidence").status_code == 200
    assert b.get(f"/runs/{run_id}/result").status_code == 403
    assert a.post(f"/runs/{run_id}/regions/confirm", json={}).status_code == 200
    assert a.post(f"/runs/{run_id}/execute").status_code == 202
    result = a.get(f"/runs/{run_id}/result")
    assert result.status_code == 200
    cands = result.json()["candidates"]
    assert cands

    # 게시 — 공개 핀이 되어도 조건 충족 체크(checks)가 유지된다(가드레일 5)
    r = a.post(f"/candidates/{cands[0]['id']}/publish")
    assert r.status_code == 200, r.text
    assert r.json().get("checks"), "게시된 뒤에도 checks가 붙어 있어야 한다"

    # 확정 리스트 → 동선 → confirmed_count
    for pid in pin_ids[:2]:
        assert a.post(f"/maps/{map_id}/shortlist", json={"pin_id": pid}).status_code in (200, 201)
    assert a.post(f"/maps/{map_id}/route").status_code in (200, 201)
    assert len(a.get(f"/maps/{map_id}/route").json()) >= 1
    assert a.get(f"/maps/{map_id}").json()["confirmed_count"] == 2
