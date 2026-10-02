"""
권한 행렬 (docs/permissions.md) — 지도 안의 모든 엔드포인트를 행위자별로 한 번씩 두드린다.

- 비로그인 → 401
- 로그인했지만 그 지도의 구성원이 아님 → **404**(존재 자체를 흘리지 않는다)
- 구성원이지만 그 액션이 롤에 없음 → 403 (run 실행계·게시는 요청한 본인만, 근거 줄 끄기는 작성자만)

비구성원·비로그인 호출은 4xx로 거절돼야 하므로 서로 부작용이 없다. 한 요청이라도 어긋나면 목록 전체를 모아 한 번에 보여 준다.
SSE(/events)는 스트림이라 test_cycle1_defects의 ASGI 헬퍼가 따로 본다.
"""

import pytest

from auth.models import User
from auth.testing import session_cookie
from integration.real_places_fixtures import (  # noqa: F401 — 픽스처는 import로 등록된다
    PLACES, _pin, _recommend, fake_planner, members, own_db, place_ids, real_client,
)


@pytest.fixture()
def world(members, place_ids, fake_planner, db_session, real_client):
    """a(지도 만든 사람, run 요청자)·b(구성원)·c(비구성원)·anon. 모든 종류의 리소스가 하나씩 있다."""
    from fastapi.testclient import TestClient

    a, b, map_id = members
    db_session.add(User(id="user_c", provider="kakao", provider_user_id="pc", display_name="외부인"))
    db_session.commit()
    c = TestClient(real_client.app, cookies=session_cookie("user_c"))
    anon = TestClient(real_client.app)
    run_id, candidates = _recommend(a, b, map_id, place_ids)
    pins = a.get(f"/maps/{map_id}/pins").json()
    pin_id = pins[0]["id"]
    assert a.post(f"/maps/{map_id}/shortlist", json={"pin_id": pin_id}).status_code in (200, 201)
    item_id = a.get(f"/maps/{map_id}/shortlist").json()[0]["id"]
    evidence = a.get(f"/runs/{run_id}/evidence").json()
    invite = a.post(f"/maps/{map_id}/invite").json()
    yield {
        "a": a, "b": b, "c": c, "anon": anon, "map": map_id, "run": run_id, "pin": pin_id, "item": item_id,
        "candidate": candidates[0]["id"], "evidence": evidence[0]["id"], "token": invite["token"],
        "new_pin": {"category": "음식점", "source": "search", "place_id": "kakao:B", "place_name": PLACES["B"][0],
                    "lat": PLACES["B"][1], "lng": PLACES["B"][2]},
    }
    c.close()
    anon.close()


def _endpoints(w):
    """(이름, method, path, json) — 지도 안 리소스를 다루는 모든 엔드포인트(SSE·공개 초대 요약·카카오 로그인 제외)."""
    m, run, pin = w["map"], w["run"], w["pin"]
    return [
        ("GET map", "GET", f"/maps/{m}", None),
        ("GET members", "GET", f"/maps/{m}/members", None),
        ("POST invite", "POST", f"/maps/{m}/invite", None),
        ("GET counts", "GET", f"/maps/{m}/counts", None),
        ("GET pins", "GET", f"/maps/{m}/pins", None),
        ("POST pin", "POST", f"/maps/{m}/pins", w["new_pin"]),
        ("DELETE pin", "DELETE", f"/pins/{pin}", None),
        ("PUT reaction", "PUT", f"/pins/{pin}/reaction", {"type": "like"}),
        ("DELETE reaction", "DELETE", f"/pins/{pin}/reaction", None),
        ("GET reactions", "GET", f"/pins/{pin}/reactions", None),
        ("GET readiness", "GET", f"/maps/{m}/recommend/readiness", None),
        ("POST run", "POST", f"/maps/{m}/runs", {"category": "음식점"}),
        ("GET evidence", "GET", f"/runs/{run}/evidence", None),
        ("PATCH evidence", "PATCH", f"/runs/{run}/evidence", {"toggle": [{"id": w["evidence"], "is_active": True}]}),
        ("POST regions/confirm", "POST", f"/runs/{run}/regions/confirm", {}),
        ("POST execute", "POST", f"/runs/{run}/execute", None),
        ("GET result", "GET", f"/runs/{run}/result", None),
        ("POST widen", "POST", f"/runs/{run}/widen", None),
        ("POST retry", "POST", f"/runs/{run}/retry", None),
        ("POST publish", "POST", f"/candidates/{w['candidate']}/publish", None),
        ("GET shortlist", "GET", f"/maps/{m}/shortlist", None),
        ("POST shortlist", "POST", f"/maps/{m}/shortlist", {"pin_id": pin}),
        ("DELETE shortlist item", "DELETE", f"/shortlist/{w['item']}", None),
        ("PUT shortlist order", "PUT", f"/maps/{m}/shortlist/order", {"item_ids": [w["item"]]}),
        ("GET route", "GET", f"/maps/{m}/route", None),
        ("POST route", "POST", f"/maps/{m}/route", None),
    ]


def _call(client, method, path, body):
    return client.request(method, path, json=body) if body is not None else client.request(method, path)


def test_anonymous_gets_401_on_every_map_endpoint(world):
    bad = []
    for name, method, path, body in _endpoints(world):
        r = _call(world["anon"], method, path, body)
        if r.status_code != 401:
            bad.append(f"{name}: {r.status_code}")
    assert not bad, "비로그인 요청이 401이 아니다: " + ", ".join(bad)


def test_outsider_gets_404_on_every_map_endpoint_and_changes_nothing(world):
    bad = []
    for name, method, path, body in _endpoints(world):
        r = _call(world["c"], method, path, body)
        if r.status_code != 404:
            bad.append(f"{name}: {r.status_code}")
    assert not bad, "비구성원 요청이 404가 아니다(존재를 흘리거나 실행됨): " + ", ".join(bad)
    # 부작용 없음 — 비구성원의 어떤 호출도 지도를 바꾸지 못했다
    a = world["a"]
    assert len(a.get(f"/maps/{world['map']}/pins").json()) == 2
    assert len(a.get(f"/maps/{world['map']}/members").json()) == 2


def test_member_who_is_not_the_requester_is_403_on_run_management_and_publish(world):
    b = world["b"]
    run, cand = world["run"], world["candidate"]
    got = {
        "execute": b.post(f"/runs/{run}/execute").status_code,
        "result": b.get(f"/runs/{run}/result").status_code,
        "widen": b.post(f"/runs/{run}/widen").status_code,
        "retry": b.post(f"/runs/{run}/retry").status_code,
        "regions/confirm": b.post(f"/runs/{run}/regions/confirm", json={}).status_code,
        "publish": b.post(f"/candidates/{cand}/publish").status_code,
    }
    # publish는 스펙이 404 AI_PIN_PRIVATE라 결정 이슈(#246)가 따로 있다 — 여기서는 403이 맞는 곳만 본다
    bad = {k: v for k, v in got.items() if k != "publish" and v != 403}
    assert not bad, f"요청자가 아닌 구성원은 run 실행계에 403이어야 한다: {bad}"
    assert got["publish"] in (403, 404), got


def test_member_can_read_and_add_evidence_but_only_the_author_can_disable_a_line(world):
    a, b, run = world["a"], world["b"], world["run"]
    assert b.get(f"/runs/{run}/evidence").status_code == 200, "근거 조회는 구성원 누구나"
    lines = a.get(f"/runs/{run}/evidence").json()
    mine = next(line for line in lines if line["permissions"]["can_disable"])
    theirs = next(line for line in b.get(f"/runs/{run}/evidence").json() if line["author_id"] != "user_b")
    assert theirs["permissions"]["can_disable"] is False
    r = b.patch(f"/runs/{run}/evidence", json={"toggle": [{"id": theirs["id"], "is_active": False}]})
    assert r.status_code == 403, "남이 쓴 줄은 뺄 수 없다(작성자만)"
    r = a.patch(f"/runs/{run}/evidence", json={"toggle": [{"id": mine["id"], "is_active": False}]})
    assert r.status_code == 200


def test_control_member_reads_every_get_endpoint(world):
    """대조군 — 비구성원 404 테스트가 '경로가 틀려서 404'가 아님을 보인다. 구성원은 같은 읽기 엔드포인트에서 200을 받는다."""
    reads = [(n, p) for n, method, p, _ in _endpoints(world) if method == "GET" and n != "GET result"]
    bad = [f"{n}: {world['a'].get(p).status_code}" for n, p in reads if world["a"].get(p).status_code != 200]
    assert not bad, bad
    assert len(reads) >= 8
