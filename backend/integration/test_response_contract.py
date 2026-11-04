"""
응답 계약 테스트 (#40) — 실제 앱이 돌려주는 JSON이 docs/api-spec.yaml의 응답 스키마와 맞는지 검증한다.

test_spec_route_coverage.py는 "경로가 있는가"만 본다. 프론트가 실서버에 붙을 때 가장 자주 깨지는 건 경로가 아니라
필드 이름·타입·필수값이라, 골든 패스의 모든 응답을 스펙의 (경로, 메서드, 상태코드) 스키마로 검증한다.

- 2xx 응답은 스펙에 선언돼 있어야 하고 스키마에 맞아야 한다.
- 에러 응답은 스펙에 선언돼 있으면 검증하고, 없으면 (docs/errors.md의 봉투 `code`,`message`만) 확인한다.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from sqlalchemy import text
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

# 알고 있고 이슈로 추적 중인 응답 불일치. (표식 문자열들) -> 이슈. 새 불일치가 생기면 실패하고, 고쳐졌는데 남아 있어도 실패한다.
KNOWN_DRIFT: dict[tuple[str, ...], str] = {
}

# 크레딧 계약 테스트(test_credits_responses_match_the_openapi_spec)만의 알려진 차이. 메인 테스트는 /credits/me를 부르지 않아
# 위 KNOWN_DRIFT에 두면 「이미 고쳐졌다」로 걸린다. 비어 가는 것이 정상이다.
KNOWN_CREDITS_DRIFT: dict[tuple[str, ...], str] = {
}

# 계약 테스트가 응답을 검증하지 못하는 엔드포인트와 이유. 스펙에 엔드포인트가 늘면 이 목록에 없는 한 실패한다.
KNOWN_UNCOVERED: dict[tuple[str, str], str] = {
    ("GET", "/auth/kakao/login"): "카카오로 가는 302 — auth 단위 테스트가 state 쿠키와 함께 검증",
    ("GET", "/auth/kakao/callback"): "외부 카카오 왕복(302) — auth 단위 테스트가 대역으로 검증",
    ("GET", "/maps/{mapId}/events"): "SSE 스트림 — realtime 테스트가 담당",
    ("GET", "/maps/{mapId}/events/me"): "SSE 스트림 — realtime 테스트가 담당",
    ("GET", "/places/external-search"): "서버 구현 전(#903) — 구현되면 이 모듈의 계약 테스트를 더하고 지운다",
    ("POST", "/auth/qa-login"): "스테이징 전용 — 테스트 앱에 없다(#788), staging 설정 앱으로 auth 테스트가 본다(#789)",
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
def advice_sessions(app_client, db_session, monkeypatch):
    """GET /runs/{runId}/advice(#587)는 요청 세션 대신 짧은 세션을 따로 연다 — 그 세션도 이 테스트 트랜잭션(db_session)
    안에서 열리게 한다. 모델 자리는 고정 응답 스텁(늘 silent)으로 둔다. 조언을 내는 대본은 테스트가 바꿔 끼운다."""
    from contextlib import contextmanager

    from agent import deps as agent_deps

    @contextmanager
    def same_session():
        yield db_session

    app_client.app.dependency_overrides[agent_deps.get_session_factory] = lambda: same_session
    monkeypatch.setattr(agent_deps, "get_llm_gateway", agent_deps.FixedAgentLlmGateway)
    return monkeypatch


@pytest.fixture()
def anon_client(app_client):
    from fastapi.testclient import TestClient

    c = TestClient(app_client.app)
    yield _Checked(c, [])
    c.close()


def _put_ad(db_session, fake_places, key: str) -> str:
    """광고 하나 — 광고 조회는 실제 places(get_ad_places)를 읽고 핀 생성은 FakePlaces를 거친다. 그래서 FakePlaces 샘플 장소와
    같은 id, 이름, 좌표의 places 행을 넣고 그 장소에 광고를 건다. 요청이 오류로 롤백돼도 남게 커밋한다(바깥 트랜잭션은 롤백)."""
    from ads.models import Ad
    from places.models import Place

    row = fake_places._row(fake_places.place_id(key))
    db_session.add(Place(id=uuid.UUID(row.place_id), source="permit", source_id=f"golden-{key}", name=row.name,
                         category=row.category, geom=f"SRID=4326;POINT({row.lng} {row.lat})", status="open"))
    ad = Ad(place_id=row.place_id, starts_at=datetime.now(timezone.utc) - timedelta(days=1),
            ends_at=datetime.now(timezone.utc) + timedelta(days=1), memo="골든 패스")
    db_session.add(ad)
    db_session.commit()
    return str(ad.id)


def test_every_response_in_the_golden_path_matches_the_openapi_spec(clients, pin_body, advice_sessions, db_session,
                                                                     fake_places):
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
    assert a.post("/places/from-link", json={"url": "https://blog.naver.com/abc"}).status_code == 422   # LINK_NOT_SUPPORTED
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
    assert b.get(f"/runs/{run_id}/advice").status_code == 403                                       # 요청자만(#587)
    assert a.get(f"/runs/{run_id}/advice").status_code == 204                                       # 낼 조언 없음

    # 추천 탭 광고(#648) — 조회(노출 집계, no-store), 클릭 기록, 광고 장소를 기존 핀 생성 API로 지도에 올리기
    ad_id = _put_ad(db_session, fake_places, "seongsu-cafe-b")
    ad_params = {"category": "카페", "lat": 37.5445, "lng": 127.0561}
    ads = a.get(f"/maps/{map_id}/ads", params=ad_params)
    assert ads.status_code == 200 and ads.headers["cache-control"] == "no-store"
    [ad] = ads.json()["ads"]
    assert (ad["ad_id"], ad["on_map"]) == (ad_id, False)
    assert a.get(f"/maps/{map_id}/ads", params={**ad_params, "category": "숙소"}).status_code == 422
    assert b.post(f"/ads/{ad_id}/clicks", json={"map_id": map_id}).status_code == 204
    assert b.post(f"/ads/{uuid.uuid4()}/clicks", json={"map_id": map_id}).status_code == 404
    place = ad["place"]
    from_ad = a.post(f"/maps/{map_id}/pins", json={"category": place["category"], "place_id": place["place_id"],
                                                   "place_name": place["name"], "lat": place["lat"], "lng": place["lng"]})
    assert from_ad.status_code == 201, from_ad.text
    assert a.get(f"/maps/{map_id}/ads", params=ad_params).json()["ads"][0]["on_map"] is True

    for pid in pin_ids[:2]:
        assert a.post(f"/maps/{map_id}/shortlist", json={"pin_id": pid}).status_code in (200, 201)
    assert a.get(f"/maps/{map_id}/shortlist").status_code == 200
    item_ids = [i["id"] for i in a.get(f"/maps/{map_id}/shortlist").json()]
    assert a.put(f"/maps/{map_id}/shortlist/order", json={"item_ids": list(reversed(item_ids))}).status_code == 200
    schedule = a.get(f"/maps/{map_id}/shortlist/schedule")
    assert schedule.status_code == 200
    payload = schedule.json()
    saved = a.put(f"/maps/{map_id}/shortlist/schedule", json={"version": payload["version"], "groups": [{"date": None, "item_ids": item_ids}]})
    assert saved.status_code == 200
    assert a.post(f"/maps/{map_id}/route").status_code in (200, 201)
    assert a.get(f"/maps/{map_id}/route").status_code == 200

    # 내보내기(#471)는 JSON이 아니라 파일 — 본문 검증 대신 형식·헤더를 직접 확인한다
    export_txt = a.get(f"/maps/{map_id}/shortlist/export")
    assert export_txt.status_code == 200 and export_txt.headers["content-type"].startswith("text/plain")
    assert export_txt.headers["content-disposition"].startswith("attachment")
    export_csv = a.get(f"/maps/{map_id}/shortlist/export", params={"format": "csv"})
    assert export_csv.status_code == 200 and export_csv.headers["content-type"].startswith("text/csv")
    assert export_csv.content.startswith("\ufeff날짜,순서,".encode())
    assert len(export_csv.text.splitlines()) == 1 + len(item_ids)
    assert a.get(f"/maps/{map_id}/shortlist/export", params={"format": "pdf"}).status_code == 422
    assert b.get(f"/maps/{map_id}/shortlist/export").status_code == 200

    assert a.delete(f"/pins/{pin_ids[0]}/reaction").status_code == 204
    assert a.post("/auth/logout").status_code == 204

    assert not problems, "응답이 스펙(docs/api-spec.yaml)과 다르다:\n- " + "\n- ".join(dict.fromkeys(problems))


def test_run_advice_matches_the_openapi_spec(clients, pin_body, advice_sessions):
    """추천 막힘 조언(#587, 코드가 정한다 #749) — 같은 카테고리 run이 3개가 되면 대상이다. 대상이 아닌 run은 204, 남의 run은 403,
    대상 run은 RunAdvice(200). 조언 종류는 깔때기 숫자로 정해지므로, 경계(recommend.api.get_run_funnel)의 결과만 바꿔
    「이미 제안·거절됨」 12곳을 만들어 exhausted 조언이 늘 나오게 한다."""
    from recommend import api as recommend_api

    real_funnel = recommend_api.get_run_funnel

    def funnel_with_many_excluded(db, *, run_id):
        funnel = real_funnel(db, run_id=run_id)
        return {**funnel, "funnel": [
            {**stage, "removed_count": 12} if stage["label"] == "이미 제안·거절됨" else stage for stage in funnel["funnel"]
        ]}

    a, b, problems = clients
    map_id = a.post("/maps", json={"title": "성수", "start_date": "2026-12-01", "end_date": "2026-12-02"}).json()["id"]
    token = a.post(f"/maps/{map_id}/invite").json()["token"]
    assert b.post(f"/invites/{token}/accept").status_code == 200
    pin_ids = [a.post(f"/maps/{map_id}/pins", json=pin_body(key)).json()["id"]
               for key in ("seongsu-kalguksu", "hongdae-ramen")]
    for c in (a, b):
        assert c.put(f"/pins/{pin_ids[0]}/reaction", json={"type": "like"}).status_code == 200
        assert c.put(f"/pins/{pin_ids[1]}/reaction", json={"type": "against", "reason_text": "별로"}).status_code == 200

    runs = [a.post(f"/maps/{map_id}/runs", json={"category": "음식점"}).json()["id"] for _ in range(3)]
    for run_id in (runs[0], runs[2]):
        assert a.post(f"/runs/{run_id}/regions/confirm", json={}).status_code == 200
        assert a.post(f"/runs/{run_id}/execute").status_code == 202

    assert a.get(f"/runs/{runs[1]}/advice").status_code == 204    # 아직 실행 전
    assert b.get(f"/runs/{runs[2]}/advice").status_code == 403
    advice_sessions.setattr(recommend_api, "get_run_funnel", funnel_with_many_excluded)
    advice = a.get(f"/runs/{runs[2]}/advice")
    assert advice.status_code == 200
    assert advice.json()["run_id"] == runs[2] and advice.json()["kind"] == "exhausted"
    segments = advice.json()["advice"][0]["segments"]   # 조언은 조각으로(#717), 숫자는 claim에서
    assert all(s["kind"] == "text" for s in segments) and "12곳" in "".join(s["text"] for s in segments)
    assert a.get(f"/runs/{runs[2]}/advice").json() == advice.json()   # run당 한 번 — 다시 열어도 같다
    assert not problems, "응답이 스펙(docs/api-spec.yaml)과 다르다:\n- " + "\n- ".join(problems)


def test_kakao_search_links_match_the_openapi_spec(clients, pin_body, app_client, fake_places):
    """카카오맵 검색 링크(#798, #800) — readiness의 curated_nearby·external_search, 결과가 적을 때의 external_search, 결과 카드의
    place_url. 추천의 장소 Gateway를 실제 구현(places.api → FakePlaces)으로 꽂는다. FakePlaces 샘플은 정예도 주소도 없어
    readiness는 0곳 + 링크(동네는 지도의 지역 이름)다. 그 뒤 샘플을 정예로 지정하면(후보 풀은 정예 장소뿐, #913) 결과는 지도에 없는
    성수 음식점 1곳 + 링크다."""
    from recommend import deps as recommend_deps

    app_client.app.dependency_overrides[recommend_deps.get_place_search_gateway] = lambda: recommend_deps.RealPlaceSearchGateway()
    app_client.app.dependency_overrides[recommend_deps.get_place_facts_gateway] = lambda: recommend_deps.RealPlaceFactsGateway()
    a, _b, problems = clients
    map_id = a.post("/maps", json={"title": "성수", "start_date": "2026-12-01", "end_date": "2026-12-02",
                                   "region": {"label": "성수동", "lat": 37.5445, "lng": 127.0561}}).json()["id"]
    pin_id = a.post(f"/maps/{map_id}/pins", json=pin_body("seongsu-kalguksu")).json()["id"]
    assert a.put(f"/pins/{pin_id}/reaction", json={"type": "like"}).status_code == 200

    readiness = a.get(f"/maps/{map_id}/recommend/readiness").json()
    assert readiness["음식점"]["curated_nearby"] == 0
    assert readiness["음식점"]["external_search"]["query"] == "성수동 맛집"
    assert "curated_nearby" not in readiness["카페"]   # 의견 핀이 없다
    fake_places.curate_all()   # 이제부터 샘플 장소가 추천 후보 풀에 들어간다

    run_id = a.post(f"/maps/{map_id}/runs", json={"category": "음식점"}).json()["id"]
    assert a.post(f"/runs/{run_id}/regions/confirm", json={}).status_code == 200
    assert a.post(f"/runs/{run_id}/execute").status_code == 202
    result = a.get(f"/runs/{run_id}/result").json()
    [candidate] = result["candidates"]
    assert candidate["place_url"].startswith("https://map.kakao.com/link/search/")
    assert result["external_search"]["query"] == "성수동 맛집"
    assert not problems, "응답이 스펙(docs/api-spec.yaml)과 다르다:\n- " + "\n- ".join(problems)


def test_notification_responses_match_the_openapi_spec(clients, db_session):
    """알림함·알림 설정(#470) — 다른 모듈의 호출 연결은 아직 없으므로 notify를 직접 불러 알림을 만든다.
    행위자 본인 제외와 꺼 둔 종류 거르기, 읽음 처리, 페이지 넘기기까지 응답이 Notification·NotificationList 스키마에 맞는다."""
    from notifications import api as notifications_api

    a, b, problems = clients
    map_id = a.post("/maps", json={"title": "성수", "start_date": "2026-12-01", "end_date": "2026-12-02"}).json()["id"]
    empty = a.get("/me/notifications")
    assert empty.status_code == 200 and empty.json() == {"items": [], "unread_count": 0}

    made = []

    def notify(user_id, type, actor_id, **kwargs):
        created = notifications_api.notify(
            db_session, user_id=user_id, type=type, map_id=map_id, map_title="성수", actor_id=actor_id,
            message=notifications_api.compose_message(type, actor_name="영희"), **kwargs)
        if created is not None:
            # 연달아 만든 알림은 시계 해상도(Windows 약 15ms)에 따라 created_at이 같아져 최신순이 uuid로 갈린다(#614).
            # 순서를 단정하려면 시각이 서로 달라야 하므로 만든 순서대로 1초씩 벌려 둔다.
            made.append(created)
            db_session.execute(
                text("UPDATE notifications SET created_at = :at WHERE id = :id"),
                {"at": datetime(2026, 12, 1, tzinfo=timezone.utc) + timedelta(seconds=len(made)), "id": created},
            )
            db_session.flush()
        return created

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
