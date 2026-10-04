"""
점검 루프 1회차 재현 테스트 (결함 D1·D2·D3·D4·D5·D7·D9).

각 테스트는 **고쳐져야 하는 올바른 동작**을 단언한다. 지금은 결함 때문에 실패하므로 `xfail(strict=True)`로 표시하고
이슈 번호를 적는다. 담당 세션이 고치면 XPASS가 되어 **실패로 바뀌므로**, 그때 `xfail`을 지워 일반 회귀 테스트로 만든다.
(strict가 없으면 고쳐진 뒤에도 조용히 남아 아무것도 지키지 못한다.)

xfail이 아닌 테스트는 "지금 맞는" 동작이다 — 헬퍼 자체가 맞는지 확인하는 대조군이다.
"""

import asyncio
import json
import uuid

import pytest

from auth.testing import session_cookie
from main import app
from places import api as places_api
from places.ratelimit import SlidingWindowLimiter

REGION = {"label": "서울", "lat": 37.5665, "lng": 126.9780}


class _Stop(Exception):
    pass


def _asgi_status(path: str, user_id: str, headers: dict | None = None) -> int | None:
    """SSE처럼 끝나지 않는 응답은 TestClient가 끊지 못해 멈춘다. ASGI 앱을 직접 불러 **응답 시작(status)만** 읽고 끊는다."""
    cookie = "; ".join(f"{k}={v}" for k, v in session_cookie(user_id).items())
    raw_headers = [(b"cookie", cookie.encode())] + [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "path": path,
        "raw_path": path.encode(), "query_string": b"", "headers": raw_headers, "server": ("testserver", 80),
        "client": ("testclient", 50000), "scheme": "http", "root_path": "",
    }
    seen: dict[str, int] = {}

    async def receive():
        await asyncio.sleep(0.2)
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            seen["status"] = message["status"]
            raise _Stop

    def _is_stop(exc: BaseException) -> bool:
        # 본문을 보내는 태스크 그룹이 예외를 ExceptionGroup으로 감싸 올린다
        children = getattr(exc, "exceptions", None)
        return isinstance(exc, _Stop) or (children is not None and all(_is_stop(c) for c in children))

    async def run():
        try:
            await app(scope, receive, send)
        except BaseException as exc:  # noqa: BLE001 — _Stop만 삼키고 나머지는 그대로 올린다
            if not _is_stop(exc):
                raise

    asyncio.run(run())
    return seen.get("status")


@pytest.fixture(autouse=True)
def _fresh_limiter(monkeypatch):
    monkeypatch.setattr(places_api, "search_limiter", SlidingWindowLimiter(1000))


@pytest.fixture()
def clients(app_client, two_users):
    from fastapi.testclient import TestClient

    a = TestClient(app_client.app, cookies=session_cookie("user_a"))
    b = TestClient(app_client.app, cookies=session_cookie("user_b"))
    yield a, b
    a.close()
    b.close()


@pytest.fixture()
def seoul_map(clients):
    a, _ = clients
    r = a.post("/maps", json={"title": "서울", "start_date": "2026-11-01", "end_date": "2026-11-03", "region": REGION})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ───────────────────────────── D1·D2 — SSE ─────────────────────────────

def test_control_member_can_subscribe_to_public_sse(clients, seoul_map):
    """대조군: 헬퍼가 구성원의 구독(200)을 제대로 본다."""
    assert _asgi_status(f"/maps/{seoul_map}/events", "user_a") == 200


def test_d1_non_member_cannot_subscribe_to_public_sse(clients, seoul_map):
    status = _asgi_status(f"/maps/{seoul_map}/events", "user_b", {"Last-Event-ID": "0"})
    assert status == 404, "비구성원은 지도가 있는지도 알 수 없어야 한다(docs/permissions.md: 비구성원 404)"


def test_d1_non_member_cannot_subscribe_to_private_sse(clients, seoul_map):
    assert _asgi_status(f"/maps/{seoul_map}/events/me", "user_b") == 404


def test_d2_sse_data_is_the_payload_itself():
    from common.events import EventLog
    from realtime.router import _sse_format

    row = EventLog(seq=7, type="pin.created", map_id="m1", channel="public", payload={"id": "p1", "place_name": "가게"})
    frame = _sse_format(row)
    data_line = next(line for line in frame.splitlines() if line.startswith("data: "))
    assert json.loads(data_line[len("data: "):]) == {"id": "p1", "place_name": "가게"}, (
        "docs/events.md·api-spec EvtPinCreated: data는 Pin 자체. 목 서버도 그렇게 보낸다"
    )


# ───────────────────────────── D3 — 확정 핀 삭제 ─────────────────────────────

@pytest.mark.xfail(strict=True, raises=AssertionError, reason="D3 — 확정 핀을 삭제하면 확정 리스트 전체가 404가 된다. #235")
def test_d3_deleting_a_confirmed_pin_does_not_break_the_shortlist(clients, seoul_map, pin_body):
    a, _ = clients
    keep = a.post(f"/maps/{seoul_map}/pins", json=pin_body("seongsu-kalguksu")).json()["id"]
    gone = a.post(f"/maps/{seoul_map}/pins", json=pin_body("hongdae-ramen")).json()["id"]
    for pid in (keep, gone):
        assert a.post(f"/maps/{seoul_map}/shortlist", json={"pin_id": pid}).status_code in (200, 201)
    assert a.delete(f"/pins/{gone}").status_code == 204

    listing = a.get(f"/maps/{seoul_map}/shortlist")
    assert listing.status_code == 200, "삭제된 핀 하나가 리스트 전체를 막으면 안 된다"
    assert [item["pin"]["id"] for item in listing.json()] == [keep]
    assert a.get(f"/maps/{seoul_map}").json()["confirmed_count"] == 1


# ───────────────────────────── D7 — pinnable ─────────────────────────────

@pytest.mark.xfail(strict=True, raises=AssertionError, reason="D7 — /places/search가 pinnable을 내려주지 않는다(pinnable_flags를 아무도 안 부른다). #238")
def test_d7_search_results_carry_pinnable(clients):
    a, _ = clients
    found = a.get("/places/search", params={"q": "해운대 밀면"})
    assert found.status_code == 200 and found.json()
    assert all("pinnable" in hit for hit in found.json()), "FE가 '아직 지원하지 않는 장소예요'를 미리 보여 주려면 필요하다"


# ───────────────────────────── D9 — 반대 사유 ─────────────────────────────

@pytest.mark.xfail(strict=True, raises=AssertionError, reason="D9 — 빈 문자열 칩만으로 사유 없는 🚫가 등록된다(가드레일 3). #236")
def test_d9_empty_chip_is_not_a_reason(clients, seoul_map, pin_body):
    a, _ = clients
    pin = a.post(f"/maps/{seoul_map}/pins", json=pin_body("hongdae-ramen")).json()["id"]
    r = a.put(f"/pins/{pin}/reaction", json={"type": "against", "reason_chip_ids": [""]})
    assert r.status_code == 422, "내용 없는 칩은 사유가 아니다"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="D9 — 칩만 있는 🚫는 근거 줄이 되지 않는다(reason_text IS NOT NULL 필터). #236")
def test_d9_chip_only_against_becomes_evidence(clients, seoul_map, pin_body):
    a, _ = clients
    pin = a.post(f"/maps/{seoul_map}/pins", json=pin_body("hongdae-ramen")).json()["id"]
    assert a.put(f"/pins/{pin}/reaction", json={"type": "against", "reason_chip_ids": ["too_spicy"]}).status_code == 200
    run = a.post(f"/maps/{seoul_map}/runs", json={"category": "음식점"})
    assert run.status_code == 202, run.text
    evidence = a.get(f"/runs/{run.json()['id']}/evidence").json()
    assert evidence, "칩으로 낸 반대 사유도 이 run의 근거에 올라와야 한다"


# ───────────────────────────── D4·D5 — wants ─────────────────────────────

def _run_recommend(db_session, lines, facts, places):
    from recommend import flows, service
    from recommend.tests.test_flows import _FakePlaceFacts, _FakePlaceSearch, _make_members, _make_region, _make_run

    run = _make_run(db_session, status="collecting_evidence")
    _make_members(db_session, user_ids=["user_1", "user_2"])
    _make_region(db_session, run, radius_m=1000)
    service.add_reaction_evidence(db_session, run_id=run.id, lines=lines)
    flows.execute_run(
        db_session, run_id=str(run.id), place_search=_FakePlaceSearch(places), place_facts=_FakePlaceFacts(facts),
    )
    return {c.place_id: c for c in service.list_candidates(db_session, str(run.id))}


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="D4 — wants=null인 선호가 '원함'으로 계산된다(문서 표는 효과 없음). #237")
def test_d4_preferred_with_unknown_direction_has_no_effect(db_session):
    from recommend.ports import PlaceStub

    candidates = _run_recommend(
        db_session,
        lines=[{"author_id": "user_2", "source": "reaction", "text": "회는 좀…", "badge": "preferred",
                "fact_key": "cuisine_raw_fish", "wants": None}],
        facts={"near_plain": {"cuisine_raw_fish": False}, "far_raw": {"cuisine_raw_fish": True}},
        places=[PlaceStub(place_id="near_plain", lat=35.0001, lng=129.0001),
                PlaceStub(place_id="far_raw", lat=35.005, lng=129.005)],
    )
    ranked = [pid for pid, _ in sorted(candidates.items(), key=lambda kv: kv[1].rank)]
    assert ranked == ["near_plain", "far_raw"], "방향을 모르는 사유는 점수에 영향이 없다 — 가까운 곳이 먼저여야 한다"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="D5 — '한식 말고'를 만족한 비한식 후보에 실패 체크(passed=False)가 붙는다. #237")
def test_d5_satisfied_exclusion_is_not_shown_as_failed(db_session):
    from recommend.ports import PlaceStub

    candidates = _run_recommend(
        db_session,
        lines=[{"author_id": "user_1", "source": "reaction", "text": "한식 말고 다른 거", "badge": "required",
                "fact_key": "cuisine_korean", "wants": False}],
        facts={"plain": {"cuisine_korean": False}},
        places=[PlaceStub(place_id="plain", lat=35.0005, lng=129.0005)],
    )
    check = next(c for c in candidates["plain"].checks if c["fact_key"] == "cuisine_korean")
    assert check["passed"] is True, "'한식 말고'를 통과한 후보가 그 조건에서 ✗로 보이면 안 된다(가드레일 5)"
    assert check["label"] not in ("False", "True"), "사람이 읽는 문구여야 한다"
