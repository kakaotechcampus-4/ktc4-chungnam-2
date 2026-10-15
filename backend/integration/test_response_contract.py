"""
응답 계약 테스트 (#40) — 실제 앱이 돌려주는 JSON이 docs/api-spec.yaml의 응답 스키마와 맞는지 검증한다.

test_spec_route_coverage.py는 "경로가 있는가"만 본다. 프론트가 실서버에 붙을 때 가장 자주 깨지는 건 경로가 아니라
필드 이름·타입·필수값이라, 골든 패스의 모든 응답을 스펙의 (경로, 메서드, 상태코드) 스키마로 검증한다.

- 2xx 응답은 스펙에 선언돼 있어야 하고 스키마에 맞아야 한다.
- 에러 응답은 스펙에 선언돼 있으면 검증하고, 없으면 (docs/errors.md의 봉투 `code`,`message`만) 확인한다.
"""

import re
import uuid
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

# 알고 있고 이슈로 추적 중인 응답 불일치. (표식 문자열들) -> 이슈. 새 불일치가 생기면 실패하고, 고쳐졌는데 남아 있어도 실패한다.
KNOWN_DRIFT: dict[tuple[str, ...], str] = {}

# 계약 테스트가 응답을 검증하지 못하는 엔드포인트와 이유. 스펙에 엔드포인트가 늘면 이 목록에 없는 한 실패한다.
KNOWN_UNCOVERED: dict[tuple[str, str], str] = {
    ("POST", "/auth/guest"): "#472 구현 PR이 골든 패스에 넣고 지운다",
    ("GET", "/runs/{runId}/advice"): "#510 agent v2 — 구현 PR이 골든 패스에 넣고 지운다",
    ("GET", "/auth/kakao/login"): "카카오로 가는 302 — auth 단위 테스트가 state 쿠키와 함께 검증",
    ("GET", "/auth/kakao/callback"): "외부 카카오 왕복(302) — auth 단위 테스트가 대역으로 검증",
    ("GET", "/maps/{mapId}/events"): "SSE 스트림 — realtime 테스트가 담당",
    ("GET", "/maps/{mapId}/events/me"): "SSE 스트림 — realtime 테스트가 담당",
}

_EXERCISED: set[tuple[str, str]] = set()   # 이 모듈의 테스트들이 실제로 호출한 (메서드, 스펙 경로)

SPEC = yaml.safe_load((Path(__file__).resolve().parents[2] / "docs" / "api-spec.yaml").read_text(encoding="utf-8"))
_REGISTRY = Registry().with_resource("urn:pingo-spec", Resource.from_contents(SPEC, default_specification=DRAFT202012))
from auth.testing import session_cookie


def _template_for(path: str, method: str) -> str | None:
    for template, ops in SPEC["paths"].items():
        if method.lower() not in ops:
            continue
        pattern = "^" + re.sub(r"\{[^}]+\}", "[^/]+", template) + "$"
        if re.match(pattern, path):
            return template
    return None


def _pointer(*parts: str) -> str:
    return "/" + "/".join(p.replace("~", "~0").replace("/", "~1") for p in parts)


def _validate(method: str, url: str, status: int, body) -> None:
    path = url.split("?")[0]
    template = _template_for(path, method)
    assert template is not None, f"스펙에 없는 경로를 호출했다: {method} {path}"
    _EXERCISED.add((method.upper(), template))
    responses = SPEC["paths"][template][method.lower()].get("responses", {})
    declared = responses.get(str(status))
    content = ((declared or {}).get("content") or {}).get("application/json")
    if declared is None or content is None:
        if 200 <= status < 300 and body not in (None, "", []):
            pytest.fail(f"{method} {template} → {status} 응답이 스펙에 선언돼 있지 않다(본문 있음)")
        if status >= 400 and isinstance(body, dict):
            assert {"code", "message"} <= set(body), f"에러 봉투가 아니다: {method} {template} {status} {body}"
        return
    ref = "urn:pingo-spec#" + _pointer("paths", template, method.lower(), "responses", str(status), "content", "application/json", "schema")
    errors = sorted(Draft202012Validator({"$ref": ref}, registry=_REGISTRY).iter_errors(body), key=lambda e: list(e.path))
    assert not errors, f"{method} {template} → {status} 응답이 스펙과 다르다: " + "; ".join(
        f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message[:120]}" for e in errors[:5]
    )


class _Checked:
    """TestClient를 감싸 모든 응답을 스펙으로 검증한다."""

    def __init__(self, client, problems):
        self._c = client
        self._problems = problems   # 첫 실패에서 멈추지 않고 전부 모아 한 번에 보여준다

    def __getattr__(self, name):
        attr = getattr(self._c, name)
        if name not in ("get", "post", "put", "patch", "delete"):
            return attr

        def call(url, *args, **kwargs):
            response = attr(url, *args, **kwargs)
            body = None
            if response.content and "json" in response.headers.get("content-type", ""):
                body = response.json()
            try:
                _validate(name.upper(), url, response.status_code, body)
            except (AssertionError, pytest.fail.Exception) as exc:
                self._problems.append(str(exc).splitlines()[0])
            return response

        return call


@pytest.fixture()
def clients(app_client, two_users):
    from fastapi.testclient import TestClient

    a = TestClient(app_client.app, cookies=session_cookie("user_a"))
    b = TestClient(app_client.app, cookies=session_cookie("user_b"))
    problems: list[str] = []
    yield _Checked(a, problems), _Checked(b, problems), problems
    a.close()
    b.close()


@pytest.fixture()
def anon_client(app_client):
    from fastapi.testclient import TestClient

    c = TestClient(app_client.app)
    yield _Checked(c, [])
    c.close()


def test_every_response_in_the_golden_path_matches_the_openapi_spec(clients, pin_body):
    a, b, problems = clients
    assert a.get("/auth/me").status_code == 200

    created = a.post("/maps", json={"title": "부산 여행", "start_date": "2026-11-01", "end_date": "2026-11-03",
                                    "region": {"label": "부산", "lat": 35.1796, "lng": 129.0756}})
    assert created.status_code == 201
    map_id = created.json()["id"]
    assert a.get("/maps").status_code == 200
    assert a.get(f"/maps/{map_id}").status_code == 200
    assert a.patch(f"/maps/{map_id}", json={"title": "부산 가을 여행"}).status_code == 200   # #465
    assert a.patch(f"/maps/{map_id}", json={}).status_code == 422
    assert (created.json()["my_role"], created.json()["created_by_me"]) == ("owner", True)  # #391

    invite = a.post(f"/maps/{map_id}/invite")
    assert invite.status_code == 201
    assert b.post(f"/invites/{invite.json()['token']}/accept").status_code == 200
    assert a.post(f"/maps/{map_id}/invite").status_code == 200   # 내 유효한 링크 재사용(#467)
    assert a.get(f"/maps/{map_id}/invites").status_code == 200
    assert b.get(f"/maps/{map_id}/invites").status_code == 403
    extra = b.post(f"/maps/{map_id}/invite")   # 구성원이 만든 링크는 따로 생긴다
    assert extra.status_code == 201
    assert a.delete(f"/invites/{extra.json()['token']}").status_code == 204
    assert a.delete(f"/invites/{extra.json()['token']}").status_code == 204   # 멱등
    assert a.get(f"/invites/{extra.json()['token']}").status_code == 410      # INVITE_REVOKED
    assert a.delete("/invites/no-such-token").status_code == 404
    assert a.get(f"/maps/{map_id}/members").status_code == 200
    # 방장 직접 넘기기(#468) — 구성원 403, 나 자신 422, 넘기고 되받는다(이후 단계는 a가 방장이라고 가정한다)
    assert b.post(f"/maps/{map_id}/owner", json={"user_id": "user_b"}).status_code == 403
    assert a.post(f"/maps/{map_id}/owner", json={"user_id": "user_a"}).status_code == 422
    assert a.post(f"/maps/{map_id}/owner", json={"user_id": "user_b"}).status_code == 200
    assert b.post(f"/maps/{map_id}/owner", json={"user_id": "user_a"}).status_code == 200

    # 이름 검색(#180) — 결과 스키마 검증 + 0건(빈 배열) + 에러 봉투 422
    assert a.get("/places/search", params={"q": "해운대", "lat": 35.16, "lng": 129.16}).status_code == 200
    assert a.get("/places/search", params={"q": "존재하지않는가게"}).json() == []
    assert a.get("/places/search", params={"q": ""}).status_code == 422

    # 지도를 눌러 핀(#473) — 자체 DB가 비어 있으면 빈 배열(지어내지 않는다), 범위 밖·누락은 422
    assert a.get("/places/nearest", params={"lat": 35.16, "lng": 129.16}).json() == []
    assert a.get("/places/nearest", params={"lat": 35.16, "lng": 129.16, "category": "카페"}).status_code == 200
    assert a.get("/places/nearest", params={"lat": 35.16}).status_code == 422
    assert a.get("/places/nearest", params={"lat": 91, "lng": 129.16}).status_code == 422

    # 지도 링크 해석(#474) — 구글(자체 DB 짝 있음)·카카오(짝 없음 → needs_search_query)·에러 봉투 422
    google_link = "https://www.google.com/maps/place/%EC%84%B1%EC%88%98+%EC%B9%BC%EA%B5%AD%EC%88%98/@37.5440,127.0560,17z/data=!8m2!3d37.5445!4d127.0561"
    found = a.post("/places/from-link", json={"url": google_link})
    assert found.status_code == 200 and len(found.json()["matches"]) == 1
    assert a.post("/places/from-link", json={"url": "https://place.map.kakao.com/1234567"}).json()["needs_search_query"] is True
    assert a.post("/places/from-link", json={"url": "https://naver.me/abc"}).status_code == 422   # LINK_NOT_SUPPORTED
    assert a.post("/places/from-link", json={"url": ""}).status_code == 422

    pin_ids = []
    for key in ("seongsu-kalguksu", "hongdae-ramen", "seongsu-cafe-a"):
        r = a.post(f"/maps/{map_id}/pins", json=pin_body(key))
        assert r.status_code == 201, r.text
        pin_ids.append(r.json()["id"])
    assert a.post(f"/maps/{map_id}/pins", json=pin_body("seongsu-kalguksu")).status_code == 409   # 에러 봉투
    assert a.post(f"/maps/{map_id}/pins", json=pin_body("seongsu-kalguksu", place_id="kakao:nope", place_name="없는 곳",
                                                        lat=35.0, lng=129.0)).status_code == 422      # PLACE_NOT_SUPPORTED
    assert a.get(f"/maps/{map_id}/pins").status_code == 200
    assert a.get(f"/maps/{map_id}/counts").status_code == 200

    assert a.put(f"/pins/{pin_ids[0]}/reaction", json={"type": "like"}).status_code == 200
    assert b.put(f"/pins/{pin_ids[0]}/reaction", json={"type": "like"}).status_code == 200
    assert a.put(f"/pins/{pin_ids[1]}/reaction", json={"type": "against"}).status_code == 422       # 사유 없음
    chips = a.get("/categories/음식점/reason-chips")
    assert chips.status_code == 200 and chips.json()                                                    # 반대 사유 칩(#312)
    assert a.get("/categories/숙소/reason-chips").json() == []
    bad_chip = {"type": "against", "reason_chip_ids": ["cafe_noisy"]}
    assert a.put(f"/pins/{pin_ids[1]}/reaction", json=bad_chip).status_code == 422                   # 다른 카테고리 칩
    chip_only = {"type": "against", "reason_chip_ids": [chips.json()[0]["id"]]}
    assert a.put(f"/pins/{pin_ids[1]}/reaction", json=chip_only).status_code == 200
    for c in (a, b):
        assert c.put(f"/pins/{pin_ids[1]}/reaction", json={"type": "against", "reason_text": "별로"}).status_code == 200

    assert a.get(f"/maps/{map_id}/recommend/readiness").status_code == 200
    run = a.post(f"/maps/{map_id}/runs", json={"category": "음식점"})
    assert run.status_code == 202
    run_id = run.json()["id"]
    assert a.get(f"/runs/{run_id}/evidence").status_code == 200
    assert a.post(f"/runs/{run_id}/regions/confirm", json={}).status_code == 200
    assert a.post(f"/runs/{run_id}/execute").status_code == 202
    result = a.get(f"/runs/{run_id}/result")
    assert result.status_code == 200
    candidates = result.json()["candidates"]
    assert candidates
    assert all(isinstance(c["lat"], float) and isinstance(c["lng"], float) for c in candidates)  # #391
    assert a.post(f"/candidates/{candidates[0]['id']}/publish").status_code == 200
    history = a.get(f"/maps/{map_id}/runs")                                                          # 지난 추천 기록(#469)
    assert history.status_code == 200 and [h["id"] for h in history.json()] == [run_id]
    assert history.json()[0]["published_count"] == 1

    for pid in pin_ids[:2]:
        assert a.post(f"/maps/{map_id}/shortlist", json={"pin_id": pid}).status_code in (200, 201)
    assert a.get(f"/maps/{map_id}/shortlist").status_code == 200
    item_ids = [i["id"] for i in a.get(f"/maps/{map_id}/shortlist").json()]
    assert a.put(f"/maps/{map_id}/shortlist/order", json={"item_ids": list(reversed(item_ids))}).status_code == 200
    assert a.post(f"/maps/{map_id}/route").status_code in (200, 201)
    assert a.get(f"/maps/{map_id}/route").status_code == 200

    # 내보내기(#471)는 JSON이 아니라 파일 — 본문 검증 대신 형식·헤더를 직접 확인한다
    export_txt = a.get(f"/maps/{map_id}/shortlist/export")
    assert export_txt.status_code == 200 and export_txt.headers["content-type"].startswith("text/plain")
    assert export_txt.headers["content-disposition"].startswith("attachment")
    export_csv = a.get(f"/maps/{map_id}/shortlist/export", params={"format": "csv"})
    assert export_csv.status_code == 200 and export_csv.headers["content-type"].startswith("text/csv")
    assert export_csv.content.startswith("\ufeff순서,".encode())
    assert len(export_csv.text.splitlines()) == 1 + len(item_ids)
    assert a.get(f"/maps/{map_id}/shortlist/export", params={"format": "pdf"}).status_code == 422
    assert b.get(f"/maps/{map_id}/shortlist/export").status_code == 200

    assert a.delete(f"/pins/{pin_ids[0]}/reaction").status_code == 204
    assert a.post("/auth/logout").status_code == 204

    unique = list(dict.fromkeys(problems))
    unexpected = [p for p in unique if not any(all(s in p for s in marks) for marks in KNOWN_DRIFT)]
    stale = [issue for marks, issue in KNOWN_DRIFT.items() if not any(all(s in p for s in marks) for p in unique)]
    assert not unexpected, "응답이 스펙(docs/api-spec.yaml)과 다르다:\n- " + "\n- ".join(unexpected)
    assert not stale, f"이미 고쳐졌으니 KNOWN_DRIFT에서 지운다: {stale}"


def test_collaboration_extras_match_the_openapi_spec(clients, anon_client, db_session, pin_body):
    """골든 패스가 안 지나가는 나머지 엔드포인트와 에러 봉투 — 초대 요약(비로그인), 이름 수정, 의견 목록·my_reaction,
    근거 수정, 반경 넓히기(상한 409)·다시 추천, 확정 취소, 핀 삭제, 탈퇴."""
    a, b, problems = clients
    map_id = a.post("/maps", json={"title": "제주", "start_date": "2026-12-01", "end_date": "2026-12-03"}).json()["id"]

    # 초대 요약은 로그인 없이 — 지도 내용은 없고, 없는 토큰은 404 봉투
    token = a.post(f"/maps/{map_id}/invite").json()["token"]
    assert anon_client.get(f"/invites/{token}").status_code == 200
    assert anon_client.get("/invites/no-such-token").status_code == 404
    assert anon_client.get("/maps").status_code == 401
    assert b.get(f"/maps/{map_id}").status_code == 404          # 비구성원은 존재를 모른다
    assert b.post(f"/invites/{token}/accept").status_code == 200

    # 이름 수정(계정 단위)
    assert a.patch("/auth/me", json={"display_name": "철수2"}).status_code == 200
    assert a.patch("/auth/me", json={"display_name": ""}).status_code == 422

    pins = []
    for key in ("seongsu-kalguksu", "seongsu-bunsik", "hongdae-ramen"):
        r = a.post(f"/maps/{map_id}/pins", json=pin_body(key))
        assert r.status_code == 201, r.text
        pins.append(r.json()["id"])
    # 숙소는 자체 DB에 없어 API로 만들 수 없다(#191) — 스키마 호환으로 남은 값이라 행을 직접 심는다
    from sqlalchemy import func

    from pins.models import Pin as PinRow
    stay_row = PinRow(
        id=uuid.uuid4(), map_id=map_id, category="숙소", kind="일반", origin="direct", place_id="stay",
        geom=func.ST_SetSRID(func.ST_MakePoint(126.5, 33.5), 4326), visibility="public", created_by="user_a",
    )
    db_session.add(stay_row)
    db_session.commit()
    stay_id = str(stay_row.id)
    # 숙소는 반응 불가(422) — 의견 목록은 빈 배열
    assert a.put(f"/pins/{stay_id}/reaction", json={"type": "like"}).status_code == 422
    assert a.get(f"/pins/{stay_id}/reactions").json() == []

    # 반응 → 의견 목록 · my_reaction · 취소
    for c in (a, b):
        assert c.put(f"/pins/{pins[0]}/reaction", json={"type": "like"}).status_code == 200
        assert c.put(f"/pins/{pins[1]}/reaction", json={"type": "against", "reason_text": "별로"}).status_code == 200
    opinions = a.get(f"/pins/{pins[0]}/reactions")
    assert opinions.status_code == 200 and len(opinions.json()) == 2
    mine = [p for p in a.get(f"/maps/{map_id}/pins").json() if p["id"] == pins[0]][0]
    assert mine["my_reaction"]["type"] == "like"
    assert b.delete(f"/pins/{pins[0]}/reaction").status_code == 204

    # 추천: 근거 수정 → 실행 → 반경 넓히기(15→20→25→30분, 그다음 409) → 다시 추천 → 게시
    run_id = a.post(f"/maps/{map_id}/runs", json={"category": "음식점"}).json()["id"]
    evidence = a.get(f"/runs/{run_id}/evidence").json()
    assert evidence
    assert a.patch(f"/runs/{run_id}/evidence", json={"toggle": [{"id": evidence[0]["id"], "is_active": False}]}).status_code == 200
    assert a.patch(f"/runs/{run_id}/evidence", json={"toggle": [{"id": evidence[0]["id"], "is_active": True}],
                                                     "add": [{"text": "조용한 곳"}]}).status_code == 200
    assert a.post(f"/runs/{run_id}/regions/confirm", json={}).status_code == 200
    assert a.post(f"/runs/{run_id}/execute").status_code == 202
    assert a.get(f"/runs/{run_id}/result").status_code == 200
    walk = [a.post(f"/runs/{run_id}/widen") for _ in range(4)]
    assert [r.status_code for r in walk] == [202, 202, 202, 409]
    assert [r.json()["default_radius_walk_min"] for r in walk[:3]] == [20, 25, 30]
    assert walk[3].json()["code"] == "WIDEN_LIMIT"
    retry = a.post(f"/runs/{run_id}/retry")
    assert retry.status_code == 202 and retry.json()["attempt_no"] >= 2
    result = a.get(f"/runs/{run_id}/result").json()
    assert result["candidates"]
    published = a.post(f"/candidates/{result['candidates'][0]['id']}/publish")
    assert published.status_code == 200
    assert b.post(f"/candidates/{result['candidates'][0]['id']}/publish").status_code in (403, 404, 409)

    # 확정 → 취소 → 핀 삭제
    item = a.post(f"/maps/{map_id}/shortlist", json={"pin_id": pins[0]})
    assert item.status_code in (200, 201)
    assert a.delete(f"/shortlist/{item.json()['id']}").status_code == 204
    assert a.delete(f"/pins/{pins[2]}").status_code == 204

    # 탈퇴 — 반응은 지워지고 핀은 남는다
    assert b.post("/auth/withdraw").status_code == 204

    unique = list(dict.fromkeys(problems))
    assert not unique, "응답이 스펙(docs/api-spec.yaml)과 다르다:\n- " + "\n- ".join(unique)


def test_feedback_responses_match_the_openapi_spec(clients):
    """서비스 피드백(#10) — 201 영수증과 422·401 에러 봉투, 시간당 상한 429."""
    a, _b, problems = clients
    assert a.post("/feedback", json={"message": "좋아요", "category": "idea"}).status_code == 201
    assert a.post("/feedback", json={"message": "   "}).status_code == 422
    assert a.post("/feedback", json={"message": "x" * 1001}).status_code == 422
    from fastapi.testclient import TestClient
    assert _Checked(TestClient(a._c.app), problems).post("/feedback", json={"message": "x"}).status_code == 401
    from feedback import api as feedback_api
    from common.ratelimit import SlidingWindowLimiter
    feedback_api.submit_limiter = SlidingWindowLimiter(1, window_s=3600.0)
    try:
        assert a.post("/feedback", json={"message": "하나"}).status_code == 201
        assert a.post("/feedback", json={"message": "둘"}).status_code == 429
    finally:
        feedback_api.submit_limiter = SlidingWindowLimiter(10, window_s=3600.0)

    unique = list(dict.fromkeys(problems))
    assert not unique, "응답이 스펙(docs/api-spec.yaml)과 다르다:\n- " + "\n- ".join(unique)


def test_map_leave_and_delete_match_the_openapi_spec(clients):
    """지도 나가기·삭제(#369) — 성공 204와 에러 봉투(구성원의 삭제 403, 넘길 사람 없는 방장의 나가기 409, 삭제 뒤 404)."""
    a, b, problems = clients
    map_id = a.post("/maps", json={"title": "강릉", "start_date": "2026-12-01", "end_date": "2026-12-02"}).json()["id"]
    token = a.post(f"/maps/{map_id}/invite").json()["token"]
    assert b.post(f"/invites/{token}/accept").status_code == 200

    assert b.delete(f"/maps/{map_id}").status_code == 403
    assert b.delete(f"/maps/{map_id}/members/me").status_code == 204
    assert a.delete(f"/maps/{map_id}/members/me").status_code == 409     # 혼자 남은 방장
    assert a.delete(f"/maps/{map_id}").status_code == 204
    assert a.get(f"/maps/{map_id}").status_code == 404

    unique = list(dict.fromkeys(problems))
    assert not unique, "응답이 스펙(docs/api-spec.yaml)과 다르다:\n- " + "\n- ".join(unique)


def test_live_pin_responses_match_the_openapi_spec(clients, pin_body):
    """실시간 핀(#386, 스펙 PinCreateLive) — 응답에 좌표·이름이 없어도 Pin 스키마에 맞고, 목록·확정 항목·동선까지 같다."""
    a, b, problems = clients
    map_id = a.post("/maps", json={"title": "성수", "start_date": "2026-12-01", "end_date": "2026-12-02"}).json()["id"]
    token = a.post(f"/maps/{map_id}/invite").json()["token"]
    assert b.post(f"/invites/{token}/accept").status_code == 200

    live = {"source": "live", "category": "음식점", "kakao_place_id": "kakao:555", "search_query": "성수 곱창", "memo": "맛있대"}
    created = a.post(f"/maps/{map_id}/pins", json=live)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["source"] == "live" and not {"lat", "lng", "place_name"} & set(body)   # 좌표·이름 없음
    live_id = body["id"]
    db_id = a.post(f"/maps/{map_id}/pins", json=pin_body("seongsu-kalguksu")).json()["id"]

    dup = a.post(f"/maps/{map_id}/pins", json=live)
    assert dup.status_code == 409 and dup.json()["detail"]["pin_id"] == live_id      # PIN_DUPLICATE
    assert a.post(f"/maps/{map_id}/pins", json={**live, "kakao_place_id": "kakao:556", "category": "숙소"}).status_code == 422
    assert a.post(f"/maps/{map_id}/pins", json={**live, "kakao_place_id": "kakao:557", "lat": 37.5}).status_code == 422

    # 핀 수정(#466) — 찍은 사람만. live 핀은 반응이 없을 때 분류도, db 핀은 메모만
    edited = a.patch(f"/pins/{live_id}", json={"memo": "웨이팅 길대", "category": "카페"})
    assert edited.status_code == 200 and (edited.json()["memo"], edited.json()["category"]) == ("웨이팅 길대", "카페")
    assert edited.json()["permissions"]["can_edit"] is True
    assert a.patch(f"/pins/{live_id}", json={"category": "음식점"}).status_code == 200
    assert a.patch(f"/pins/{db_id}", json={"memo": "점심에"}).status_code == 200
    assert a.patch(f"/pins/{db_id}", json={"category": "카페"}).status_code == 422          # 장소가 정한다
    assert b.patch(f"/pins/{live_id}", json={"memo": "남의 핀"}).status_code == 403
    assert a.patch(f"/pins/{live_id}", json={}).status_code == 422

    listed = a.get(f"/maps/{map_id}/pins").json()
    assert {p["id"] for p in listed} == {live_id, db_id}
    assert b.put(f"/pins/{live_id}/reaction", json={"type": "like"}).status_code == 200

    # 라이브 핀 승격(#501) — 구성원 누구나. 짝이 없으면 200 변화 없음, 이미 그 장소 핀이 있으면 409, 짝이 있으면 같은 id의 db 핀으로
    bunsik = pin_body("seongsu-bunsik")
    hint = {"place_name": bunsik["place_name"], "lat": bunsik["lat"], "lng": bunsik["lng"], "address": "서울 성동구 성수동"}
    nowhere = b.post(f"/pins/{live_id}/resolve", json={"place_name": "없는 가게", "lat": 35.0, "lng": 129.0})
    assert nowhere.status_code == 200 and nowhere.json()["source"] == "live"
    kalguksu = pin_body("seongsu-kalguksu")
    dup = b.post(f"/pins/{live_id}/resolve", json={"place_name": kalguksu["place_name"], "lat": kalguksu["lat"], "lng": kalguksu["lng"]})
    assert dup.status_code == 409 and dup.json()["detail"]["pin_id"] == db_id
    assert b.post(f"/pins/{live_id}/resolve", json={"place_name": "x", "lat": 95, "lng": 127}).status_code == 422
    other = a.post(f"/maps/{map_id}/pins", json={**live, "kakao_place_id": "kakao:777"}).json()["id"]
    assert b.put(f"/pins/{other}/reaction", json={"type": "like"}).status_code == 200
    promoted = b.post(f"/pins/{other}/resolve", json=hint)
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["id"] == other and promoted.json()["source"] == "db" and promoted.json()["place_name"] == bunsik["place_name"]
    assert promoted.json()["my_reaction"]["type"] == "like"                            # 반응은 그대로
    assert b.post(f"/pins/{other}/resolve", json=hint).status_code == 200              # 이미 db 핀 — 변화 없음
    assert b.delete(f"/pins/{other}").status_code == 204

    for pin_id in (live_id, db_id):
        assert a.post(f"/maps/{map_id}/shortlist", json={"pin_id": pin_id}).status_code == 201
    shortlist = a.get(f"/maps/{map_id}/shortlist").json()
    assert {item["pin"]["id"] for item in shortlist} == {live_id, db_id}            # 확정 리스트에는 남는다
    routes = a.post(f"/maps/{map_id}/route")
    assert routes.status_code == 200
    ordered = [pin_id for route in routes.json() for pin_id in route["ordered_pin_ids"]]
    assert live_id not in ordered                                                     # 동선에서는 빠진다

    unique = list(dict.fromkeys(problems))
    assert not unique, "응답이 스펙(docs/api-spec.yaml)과 다르다:\n- " + "\n- ".join(unique)


def test_agent_endpoints_match_the_openapi_spec(clients, db_session, pin_body):
    """v2 계획 보조 에이전트(#531) — 바텀시트 상태, 열람, 수락(422·409 포함), 닫기, 모드 끄고 켜기. 제안은 관찰 흐름의
    저장 단계(스냅샷 → 탐지 → 템플릿 → 저장)를 이 테스트 세션에서 그대로 밟아 만든다(observe_map은 자기 세션을 연다)."""
    from datetime import datetime, timedelta, timezone

    from agent import core, service, snapshot

    a, b, problems = clients
    map_id = a.post("/maps", json={"title": "여수", "start_date": "2026-12-01", "end_date": "2026-12-02"}).json()["id"]
    assert b.get(f"/maps/{map_id}/agent").status_code == 404                     # 비구성원은 존재를 모른다
    token = a.post(f"/maps/{map_id}/invite").json()["token"]
    assert b.post(f"/invites/{token}/accept").status_code == 200

    empty = a.get(f"/maps/{map_id}/agent")
    assert empty.status_code == 200
    assert empty.json() == {"settings": {"enabled": True, "updated_by": None, "updated_at": None},
                            "active_suggestion": None, "has_unseen": False, "summaries": []}

    for key in ("seongsu-kalguksu", "seongsu-bunsik"):   # 음식점만 2곳 확정 → 카페·관광지 공백(6.5)
        pin_id = a.post(f"/maps/{map_id}/pins", json=pin_body(key)).json()["id"]
        assert a.post(f"/maps/{map_id}/shortlist", json={"pin_id": pin_id}).status_code == 201

    def suggest(category: str) -> str:
        now = datetime.now(timezone.utc)
        snap = snapshot.build(db_session, map_id, now)
        sig = next(s for s in core.detect_all(snap, now, timedelta(hours=1))
                   if s.diagnosis == "category_gap" and s.category == category)
        sid = service.insert_suggestion(db_session, map_id=map_id, run_id=None, signal=sig,
                                        draft=core.render_template(sig), now=now, shadow=False)
        db_session.commit()
        return str(sid)

    first = suggest("카페")
    state = a.get(f"/maps/{map_id}/agent").json()
    assert state["active_suggestion"]["title"] == "확정 리스트에 카페가 아직 없어요" and state["has_unseen"] is True
    assert a.post(f"/agent/suggestions/{first}/view").status_code == 204
    assert a.post(f"/agent/suggestions/{first}/view").status_code == 204          # 멱등
    assert a.get(f"/maps/{map_id}/agent").json()["has_unseen"] is False
    assert b.get(f"/maps/{map_id}/agent").json()["has_unseen"] is True             # 사람마다
    assert a.post("/agent/suggestions/no-such-id/view").status_code == 404
    assert a.post(f"/agent/suggestions/{first}/accept", json={"action_index": 9}).status_code == 422
    accepted = a.post(f"/agent/suggestions/{first}/accept", json={"action_index": 0})
    assert accepted.status_code == 200
    assert accepted.json()["action"] == {"index": 0, "type": "open_recommend", "label": "카페 추천 받기",
                                         "params": {"category": "카페"}}
    assert b.post(f"/agent/suggestions/{first}/accept", json={"action_index": 0}).status_code == 409
    assert b.post(f"/agent/suggestions/{first}/dismiss").status_code == 409

    second = suggest("관광지")
    assert b.post(f"/agent/suggestions/{second}/dismiss").status_code == 204
    assert a.get(f"/maps/{map_id}/agent").json()["active_suggestion"] is None

    off = b.put(f"/maps/{map_id}/agent/settings", json={"enabled": False})
    assert off.status_code == 200 and off.json()["enabled"] is False and off.json()["updated_by"] == "user_b"
    assert a.get(f"/maps/{map_id}/agent").json()["settings"]["enabled"] is False
    assert a.put(f"/maps/{map_id}/agent/settings", json={"enabled": True}).json()["enabled"] is True


def test_notification_responses_match_the_openapi_spec(clients, db_session):
    """알림함·알림 설정(#470) — 다른 모듈의 호출 연결은 아직 없으므로 notify를 직접 불러 알림을 만든다.
    행위자 본인 제외와 꺼 둔 종류 거르기, 읽음 처리, 페이지 넘기기까지 응답이 Notification·NotificationList 스키마에 맞는다."""
    from notifications import api as notifications_api

    a, b, problems = clients
    map_id = a.post("/maps", json={"title": "성수", "start_date": "2026-12-01", "end_date": "2026-12-02"}).json()["id"]
    empty = a.get("/me/notifications")
    assert empty.status_code == 200 and empty.json() == {"items": [], "unread_count": 0}

    def notify(user_id, type, actor_id, **kwargs):
        return notifications_api.notify(
            db_session, user_id=user_id, type=type, map_id=map_id, map_title="성수", actor_id=actor_id,
            message=notifications_api.compose_message(type, actor_name="영희"), **kwargs)

    assert notify("user_a", "pin_reaction", "user_b", pin_id="pin_1") is not None
    assert notify("user_a", "member_joined", "user_b") is not None
    assert notify("user_a", "pin_reaction", "user_a", pin_id="pin_1") is None        # 내가 한 일은 나에게 없다
    assert notify("user_b", "owner_changed", None) is not None

    listed = a.get("/me/notifications", params={"limit": 1})
    assert listed.status_code == 200
    body = listed.json()
    assert body["unread_count"] == 2 and len(body["items"]) == 1 and body["next_before"]
    assert body["items"][0]["type"] == "member_joined" and body["items"][0]["read"] is False
    older = a.get("/me/notifications", params={"limit": 1, "before": body["next_before"]}).json()
    assert older["items"][0]["type"] == "pin_reaction" and older["items"][0]["pin_id"] == "pin_1"
    assert "next_before" not in older
    assert a.get("/me/notifications", params={"limit": 0}).status_code == 422
    assert a.get("/me/notifications", params={"before": "nope"}).status_code == 422

    assert a.post("/me/notifications/read", json={"ids": [body["items"][0]["id"]]}).status_code == 204
    assert a.get("/me/notifications", params={"unread_only": True}).json()["unread_count"] == 1
    assert a.post("/me/notifications/read", json={"ids": ["x"] * 101}).status_code == 422
    assert b.get("/me/notifications").json()["unread_count"] == 1                    # 남의 알림은 읽히지 않는다
    assert a.post("/me/notifications/read").status_code == 204                       # 생략하면 전부
    assert a.get("/me/notifications").json()["unread_count"] == 0

    prefs = a.get("/me/notification-prefs")
    assert prefs.status_code == 200 and all(p["enabled"] for p in prefs.json()["prefs"])
    off = a.put("/me/notification-prefs", json={"prefs": [{"type": "pin_reaction", "enabled": False}]})
    assert off.status_code == 200 and off.json()["prefs"][0] == {"type": "pin_reaction", "enabled": False}
    assert a.put("/me/notification-prefs", json={"prefs": []}).status_code == 422
    assert notify("user_a", "pin_reaction", "user_b", pin_id="pin_1") is None        # 끈 종류는 만들지 않는다
    assert a.get("/me/notifications").json()["unread_count"] == 0

    unique = list(dict.fromkeys(problems))
    assert not unique, "응답이 스펙(docs/api-spec.yaml)과 다르다:\n- " + "\n- ".join(unique)


def test_zz_every_spec_operation_is_exercised_by_a_contract_test():
    """계약 테스트가 지나가지 않는 엔드포인트는 응답 모양이 스펙과 맞는지 아무도 모른다. 스펙에 엔드포인트를 추가하면
    이 테스트가 실패해 호출을 골든 패스에 넣게 한다. (파일 안에서 마지막에 실행돼야 한다 — 이름의 zz.)"""
    spec_ops = {(m.upper(), p) for p, ops in SPEC["paths"].items() for m in ops if m in ("get", "post", "put", "patch", "delete")}
    uncovered = spec_ops - _EXERCISED
    unexpected = uncovered - set(KNOWN_UNCOVERED)
    stale = set(KNOWN_UNCOVERED) - uncovered
    assert not unexpected, f"계약 테스트가 지나가지 않는 엔드포인트: {sorted(unexpected)}"
    assert not stale, f"이제 지나가니 KNOWN_UNCOVERED에서 지운다: {sorted(stale)}"


def test_the_validator_actually_rejects_a_wrong_shape():
    """검증기가 조용히 다 통과시키는 게 아닌지 — 필수 필드가 빠진 Pin은 실패해야 한다."""
    with pytest.raises(AssertionError, match="스펙과 다르다"):
        _validate("GET", "/maps/m1/pins", 200, [{"id": "x"}])


# 응답 객체 스키마는 `required`를 선언해야 한다 — 비어 있으면 핸들러가 `{}`를 돌려줘도 위 검증이 통과하고,
# 생성되는 FE 타입이 전부 optional이 된다(멘토 리뷰, PR #152). 의도적으로 비워 둔 스키마는 이유와 함께 여기에 둔다.
NO_REQUIRED_OK: dict[str, str] = {
    "Permissions": "맥락마다 쓰는 필드가 다르다(can_disable은 근거 줄 전용, can_publish는 후보 전용) — 필드별로 선택",
    "AgentAction.params": "버튼 종류(type)마다 쓰는 필드가 다르다(category는 추천과 검색, pin_ids는 핀 보기, run_id는 반경과 근거) — 필드별로 선택 (#510)",
}


def _response_object_schemas_without_required() -> set[str]:
    schemas = SPEC["components"]["schemas"]
    seen: set[str] = set()
    bad: set[str] = set()

    def walk(sch, name: str) -> None:
        if not isinstance(sch, dict):
            return
        if "$ref" in sch:
            ref = sch["$ref"].rsplit("/", 1)[-1]
            if ref not in seen:
                seen.add(ref)
                walk(schemas[ref], ref)
            return
        for key in ("oneOf", "anyOf", "allOf"):
            for sub in sch.get(key, []):
                walk(sub, name)
        if sch.get("type") == "array":
            walk(sch.get("items"), name)
        if "properties" in sch:
            if not sch.get("required"):
                bad.add(name)
            for prop, sub in sch["properties"].items():
                walk(sub, f"{name}.{prop}")

    for ops in SPEC["paths"].values():
        for op in ops.values():
            if not isinstance(op, dict):
                continue
            for status, resp in op.get("responses", {}).items():
                if not str(status).startswith("2"):
                    continue
                if "$ref" in resp:
                    resp = SPEC["components"]["responses"][resp["$ref"].rsplit("/", 1)[-1]]
                walk(((resp.get("content") or {}).get("application/json") or {}).get("schema"), "(inline)")
    return bad


def test_response_object_schemas_declare_required():
    missing = sorted(_response_object_schemas_without_required() - set(NO_REQUIRED_OK))
    assert not missing, f"응답 스키마에 required가 없다 — 항상 오는 필드를 채우거나 NO_REQUIRED_OK에 이유와 함께 등록: {missing}"


def test_no_required_exceptions_are_still_needed():
    stale = sorted(set(NO_REQUIRED_OK) - _response_object_schemas_without_required())
    assert not stale, f"required가 채워져 예외가 필요 없다 — NO_REQUIRED_OK에서 지운다: {stale}"
