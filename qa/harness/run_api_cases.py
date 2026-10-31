"""API edge 케이스 실행기 — 두 가지로 돈다.

- 로컬(기본): 같은 프로세스의 앱(TestClient) + 격리 DB(pingo_eval) + 실제 모델(추천 구조화 호출 포함). 사용자는 DB에 직접
  만들고, 장소는 DB에서 고른다.
- HTTP(`--base-url`): 띄워 둔 서버에 실제 HTTP로 보낸다(#788). 백그라운드 작업, 쿠키, 프록시, 인스턴스마다 따로 세는 상한처럼
  배포에서만 생기는 문제가 여기서 보인다. 이 모드는 backend를 import하지 않는다. 사용자는 스테이징 전용 QA 로그인
  (`POST /auth/qa-login`, 헤더 X-QA-Login-Secret = 환경 변수 QA_LOGIN_SECRET)으로 만들고, 장소는 `GET /places/search`의
  핀을 만들 수 있는(pinnable) 결과에서 고른다. 서버 메모리를 직접 비우는 케이스(L05)는 건너뛴다.

키·시크릿은 출력하지 않는다. 결과는 표준출력에 `ID | 판정 | 메모`로 낸다(qa/results/<날짜>.md에 옮겨 적는다).

usage:
  로컬(backend 폴더에서): PYTHONUTF8=1 DATABASE_URL=postgresql://pingo:pingo@localhost:5432/pingo_eval python ../qa/harness/run_api_cases.py [ID ...]
  HTTP: PYTHONUTF8=1 QA_LOGIN_SECRET=... python qa/harness/run_api_cases.py --base-url http://localhost:8000 [ID ...]
판정: PASS(기대대로) | FAIL(기대와 다름 — 버그 후보) | INFO(관찰만) | SKIP(이 모드에서 못 봄) | ERR(하네스 오류)
"""
import json
import os
import sys
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor

SEONGSU = {"label": "성수", "lat": 37.5446, "lng": 127.0557}
RESULTS = []
BASE_URL = None          # --base-url이 있으면 HTTP 모드
RESULT_WAIT_SEC = 120    # 추천 실행(백그라운드) 결과를 기다리는 시간. 실제 모델 ② 호출이 들어 있다


def _app():
    """로컬 모드에서만 backend를 import한다 — HTTP 모드는 backend 없이 돈다(경로는 __main__이 넣는다)."""
    from main import app
    return app


def client(cookies=None):
    """클라이언트 하나. 같은 쿠키로 여럿을 만들면 동시 요청이 된다. 로컬은 TestClient, HTTP는 httpx."""
    if BASE_URL:
        import httpx
        return httpx.Client(base_url=BASE_URL, cookies=cookies, timeout=60)
    from fastapi.testclient import TestClient
    return TestClient(_app(), cookies=cookies)


def user(tag=""):
    if BASE_URL:
        c = client()
        r = c.post("/auth/qa-login", headers={"X-QA-Login-Secret": os.environ["QA_LOGIN_SECRET"]},
                   json={"display_name": f"QA {uuid.uuid4().hex[:6]}{tag}"})
        assert r.status_code == 201, f"QA 로그인 실패 {r.status_code}"
        return r.json()["id"], c
    from auth.testing import ensure_users, session_cookie
    from common import database
    uid = f"qa_{uuid.uuid4().hex[:8]}{tag}"
    with database.SessionLocal() as db:
        ensure_users(db, uid, display_names={uid: f"QA {uid[-6:]}"})
        db.commit()
    return uid, client(session_cookie(uid))


# HTTP 모드의 장소 검색어. 카테고리마다 성수 근처에서 자체 DB 장소가 나오는 말이고, fact는 그 라벨이 붙었을 법한 말이다.
# DB를 읽지 않으니 라벨로 거르지는 못한다.
SEARCH_WORDS = {"음식점": "성수 맛집", "카페": "성수 카페", "관광지": "성수 갤러리"}
FACT_WORDS = {"cuisine_western": "성수 파스타"}
_search_cache: dict = {}
_searcher = None


def place(cat="음식점", skip=0, fact=None):
    """(이름, 위도, 경도, 카테고리). 로컬은 DB에서 성수 가까운 순, HTTP는 검색 결과 중 핀을 만들 수 있는 것의 skip번째."""
    if BASE_URL:
        global _searcher
        if _searcher is None:
            _searcher = user("s")[1]
        q = FACT_WORDS.get(fact) or SEARCH_WORDS[cat]
        if q not in _search_cache:   # 결과는 이 실행의 메모리에만 둔다(#53)
            r = _searcher.get("/places/search", params={"q": q, "lat": SEONGSU["lat"], "lng": SEONGSU["lng"], "limit": 15})
            assert r.status_code == 200, f"장소 검색 {r.status_code}"
            _search_cache[q] = [x for x in r.json() if x.get("pinnable", True) and x.get("category") == cat]
        x = _search_cache[q][skip]
        return x["place_name"], x["lat"], x["lng"], cat
    import sqlalchemy as sa
    from common import database
    q = """select name, ST_Y(geom::geometry), ST_X(geom::geometry), category from places p
           where curated and status='open' and category=:c"""
    if fact:
        q += " and exists (select 1 from place_facts f where f.place_id=p.id and f.fact_key=:fk and f.value=to_jsonb(true))"
    q += " order by ST_Distance(geom, ST_SetSRID(ST_MakePoint(127.0557,37.5446),4326)::geography) offset :s limit 1"
    with database.SessionLocal() as db:
        return db.execute(sa.text(q), {"c": cat, "s": skip, "fk": fact}).first()


def result(c, rid):
    """추천 결과. 실행은 백그라운드라 HTTP에서는 409 RUN_NOT_FINISHED가 끝날 때까지 다시 묻는다. 로컬 TestClient는 응답 전에
    백그라운드 작업을 끝내서 이 차이가 보이지 않았다."""
    deadline = time.monotonic() + RESULT_WAIT_SEC
    while True:
        r = c.get(f"/runs/{rid}/result")
        if r.status_code != 409 or r.json().get("code") != "RUN_NOT_FINISHED" or time.monotonic() > deadline:
            return r
        time.sleep(1)


def new_map(c, start="2026-11-10", end="2026-11-12", **kw):
    r = c.post("/maps", json={"title": "QA 지도", "start_date": start, "end_date": end, "region": SEONGSU, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def add_pin(c, mid, skip=0, cat="음식점", fact=None):
    name, lat, lng, cat = place(cat, skip, fact)
    r = c.post(f"/maps/{mid}/pins", json={"category": cat, "place_id": "hint", "place_name": name, "lat": lat, "lng": lng})
    return r


def rec(cid, verdict, note=""):
    RESULTS.append((cid, verdict, note))
    print(f"{cid} | {verdict} | {note}", flush=True)


def check(cid, cond, ok, bad):
    rec(cid, "PASS" if cond else "FAIL", ok if cond else bad)


# ───────── 케이스 ─────────
def a01_a02():
    _, c = user(); mid = new_map(c); pin = add_pin(c, mid).json()["id"]
    for n in (139, 140):
        r = c.put(f"/pins/{pin}/reaction", json={"type": "against", "reason_text": "가" * n})
        check(f"A01.{n}", r.status_code == 200, "200", f"{r.status_code} {r.text[:120]}")
    r = c.put(f"/pins/{pin}/reaction", json={"type": "against", "reason_text": "가" * 141})
    check("A02", r.status_code == 422, "141자 422", f"{r.status_code} {r.text[:120]}")


def a03():
    _, c = user(); mid = new_map(c); pin = add_pin(c, mid).json()["id"]
    for label, txt in (("empty", ""), ("spaces", "   "), ("newline", "\n\t "), ("missing", None)):
        body = {"type": "against"}
        if txt is not None:
            body["reason_text"] = txt
        r = c.put(f"/pins/{pin}/reaction", json=body)
        check(f"A03.{label}", r.status_code == 422, "422", f"{r.status_code} {r.text[:120]}")


def a04_a05():
    _, c = user(); mid = new_map(c); pin = add_pin(c, mid).json()["id"]
    cases = {
        "emoji": "맛있어요 😋🍜 또 가고 싶어요", "zwj": "아이랑 👨‍👩‍👧‍👦 가기 좋아요",
        "nfd": unicodedata.normalize("NFD", "한식이 좋아요"), "zerowidth": "조​용​한 곳",
        "mixed": "ラーメン이 먹고 싶어요 ramen", "html": "<b>시끄러워요</b><script>alert(1)</script>",
        "sql": "'; DROP TABLE places; --", "url": "https://evil.example/ 여기 가요",
    }
    for k, txt in cases.items():
        r = c.put(f"/pins/{pin}/reaction", json={"type": "against", "reason_text": txt})
        if r.status_code != 200:
            rec(f"A04/5.{k}", "FAIL", f"{r.status_code} {r.text[:120]}"); continue
        back = c.get(f"/pins/{pin}/reactions").json()
        stored = next((x.get("reason_text") for x in back if x.get("reason_text") is not None), None)
        note = "저장값 원문과 동일" if stored == txt else f"저장값 변형됨: {stored!r}"
        rec(f"A04/5.{k}", "PASS" if stored == txt else "INFO", note)


def a06_a09():
    _, c = user(); mid = new_map(c); pin = add_pin(c, mid).json()["id"]
    c.put(f"/pins/{pin}/reaction", json={"type": "like", "reason_text": "한식이 좋아요"})
    run = c.post(f"/maps/{mid}/runs", json={"category": "음식점"})
    rid = run.json()["id"]
    r = c.patch(f"/runs/{rid}/evidence", json={"add": [{"text": t} for t in ["한식", "조용한 곳", "주차 가능", "웨이팅 짧음", "가성비"]]})
    check("A06", r.status_code == 200, "5줄 200", f"{r.status_code} {r.text[:150]}")
    r = c.patch(f"/runs/{rid}/evidence", json={"add": [{"text": f"조건{i}"} for i in range(6)]})
    check("A07", r.status_code == 422, "6줄 422", f"{r.status_code} (스펙은 422) {r.text[:150]}")
    n = 0
    last = None
    for i in range(8):
        last = c.patch(f"/runs/{rid}/evidence", json={"add": [{"text": f"추가{i}"}]})
        n += last.status_code == 200
    check("A08", last.status_code == 409 and last.json().get("code") == "EVIDENCE_LIMIT",
          "run당 상한 409 EVIDENCE_LIMIT", f"추가 요청 8번 모두 후 마지막 {last.status_code} {last.text[:120]} (성공 {n}회; 스펙은 run당 10줄)")
    for label, txt in (("empty", ""), ("len141", "가" * 141)):
        r = c.patch(f"/runs/{rid}/evidence", json={"add": [{"text": txt}]})
        check(f"A09.{label}", r.status_code == 422, "422", f"{r.status_code} {r.text[:120]}")


def a10_a12():
    _, c = user()
    def mk(title="t", **kw):
        return c.post("/maps", json={"title": title, "start_date": "2026-11-10", "end_date": "2026-11-12", "region": SEONGSU, **kw})
    check("A10.100", mk("가" * 100).status_code == 201, "100자 201", "100자 실패")
    r = mk("가" * 101); check("A10.101", r.status_code == 422, "101자 422", f"{r.status_code}")
    r = mk(""); check("A10.empty", r.status_code == 422, "빈 제목 422", f"{r.status_code}")
    r = mk("제목 😋🍜"); check("A10.emoji", r.status_code == 201, "이모지 201", f"{r.status_code}")
    def mk2(s, e):
        return c.post("/maps", json={"title": "d", "start_date": s, "end_date": e, "region": SEONGSU})
    r = mk2("2026-11-10", "2026-11-10"); check("A11.sameday", r.status_code == 201, "같은 날 201", f"{r.status_code}")
    r = mk2("2026-11-12", "2026-11-10"); check("A11.inverted", r.status_code == 422, "종료<시작 422", f"{r.status_code}")
    r = mk2("2026-11-10", "2028-11-10"); rec("A11.2years", "INFO", f"2년짜리 여행 → {r.status_code}")
    r = mk2("2020-01-01", "2020-01-03"); rec("A11.past", "INFO", f"과거 날짜 → {r.status_code}")
    r = c.post("/maps", json={"title": "n", "region": SEONGSU}); rec("A11.nodates", "INFO", f"날짜 없음 → {r.status_code}")
    mid = new_map(c)
    r = c.patch(f"/maps/{mid}", json={"start_date": "2027-01-01"}); check("A12", r.status_code == 422, "start만 end 뒤로 PATCH 422", f"{r.status_code} {r.text[:120]}")


def a13_a14():
    _, c = user(); mid = new_map(c)
    r1 = add_pin(c, mid); r2 = add_pin(c, mid)
    check("A13.seq", r1.status_code == 201 and r2.status_code == 409 and r2.json().get("code") == "PIN_DUPLICATE",
          "두 번째 409 PIN_DUPLICATE", f"{r1.status_code}/{r2.status_code} {r2.text[:100]}")
    mid2 = new_map(c); name, lat, lng, cat = place("카페", 3)
    def go(_):
        _, cc = user(); return None
    codes = []
    def one(_):
        cl = client(c.cookies)
        r = cl.post(f"/maps/{mid2}/pins", json={"category": cat, "place_id": "hint", "place_name": name, "lat": lat, "lng": lng})
        codes.append(r.status_code)
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(one, range(4)))
    check("A13.race", sorted(codes).count(201) == 1 and all(x in (201, 409) for x in codes), f"동시 4요청 → {sorted(codes)}", f"동시 4요청 → {sorted(codes)}")
    r = c.post(f"/maps/{mid}/pins", json={"category": "숙소", "place_id": "hint", "place_name": "x", "lat": 37.5, "lng": 127.0})
    check("A14", r.status_code == 422, "숙소 핀 422", f"{r.status_code} {r.text[:100]}")


def b01_b03():
    uid, c = user()
    ids = [new_map(c) for _ in range(20)]
    r = c.post("/maps", json={"title": "21", "start_date": "2026-11-10", "end_date": "2026-11-12", "region": SEONGSU})
    check("B01", r.status_code in (403, 409, 422) and "MAP_LIMIT" in r.text, "21번째 MAP_LIMIT", f"{r.status_code} {r.text[:120]}")
    _, owner = user(); omid = new_map(owner); tok = owner.post(f"/maps/{omid}/invite").json()["token"]
    r = c.post(f"/invites/{tok}/accept")
    check("B02", "MAP_LIMIT" in r.text, "20개 보유자 수락 MAP_LIMIT", f"{r.status_code} {r.text[:120]}")
    d = c.delete(f"/maps/{ids[0]}")
    r = c.post(f"/invites/{tok}/accept")
    check("B03", d.status_code == 204 and r.status_code == 200, "삭제 후 수락 200", f"del {d.status_code}, accept {r.status_code} {r.text[:100]}")


def b04_b08():
    uid, c = user(); mid = new_map(c)
    for cat in ("음식점", "카페", "관광지"):   # 카테고리마다 ♥ 핀이 있어야 readiness를 통과한다
        pin = add_pin(c, mid, cat=cat).json()["id"]
        c.put(f"/pins/{pin}/reaction", json={"type": "like", "reason_text": "조용해서 좋아요"})
    codes = []
    for i in range(11):
        cat = ("음식점", "카페", "관광지")[i % 3]
        r = c.post(f"/maps/{mid}/runs", json={"category": cat}); codes.append(r.status_code)
    last = r
    check("B04", codes[:10] == [202] * 10 and codes[10] == 429 and last.json().get("code") == "RETRY_LIMIT",
          "10회까지 202, 11번째 429 RETRY_LIMIT", f"{codes} {last.text[:150]}")
    rid = c.get(f"/maps/{mid}/runs").json()[0]["id"]
    r = c.get(f"/runs/{rid}/result")
    check("B08", r.status_code == 409 and r.json().get("code") == "RUN_NOT_FINISHED", "execute 전 409 RUN_NOT_FINISHED", f"{r.status_code} {r.text[:120]}")


def c01_c05():
    uid, c = user(); mid = new_map(c); pin = add_pin(c, mid).json()["id"]
    def react(i):
        cl = client(c.cookies)
        return cl.put(f"/pins/{pin}/reaction", json={"type": "against", "reason_text": f"동시{i}"}).status_code
    with ThreadPoolExecutor(6) as ex:
        codes = list(ex.map(react, range(6)))
    n = len(c.get(f"/pins/{pin}/reactions").json())
    check("C01", all(x == 200 for x in codes) and n == 1, f"동시 6개 PUT → 모두 200, 반응 1개", f"{codes}, 저장 {n}개")
    c.put(f"/pins/{pin}/reaction", json={"type": "like", "reason_text": "좋아요"})
    run = c.post(f"/maps/{mid}/runs", json={"category": "음식점"}); rid = run.json()["id"]
    c.post(f"/runs/{rid}/regions/confirm", json={})
    def exe(_):
        return client(c.cookies).post(f"/runs/{rid}/execute").status_code
    with ThreadPoolExecutor(3) as ex:
        codes = list(ex.map(exe, range(3)))
    res = result(c, rid)
    check("C03", all(x in (200, 202, 409) for x in codes) and res.status_code == 200, f"execute 3연타 → {codes}, result {res.status_code}", f"{codes} result {res.status_code} {res.text[:100]}")
    cands = res.json().get("candidates", [])
    if cands:
        cid = cands[0]["id"]
        def pub(_):
            return client(c.cookies).post(f"/candidates/{cid}/publish").status_code
        with ThreadPoolExecutor(3) as ex:
            codes = list(ex.map(pub, range(3)))
        pins = [p for p in c.get(f"/maps/{mid}/pins").json() if p.get("source") != "search" or True]
        check("C04", all(x in (200, 409) for x in codes), f"publish 3연타 → {codes}", f"{codes}")


def l01_l04():
    uid, c = user(); mid = new_map(c); pin = add_pin(c, mid).json()["id"]
    c.put(f"/pins/{pin}/reaction", json={"type": "like", "reason_text": "한식이 좋아요"})
    rid = c.post(f"/maps/{mid}/runs", json={"category": "음식점"}).json()["id"]
    c.post(f"/runs/{rid}/regions/confirm", json={}); c.post(f"/runs/{rid}/execute")
    tok = c.post(f"/maps/{mid}/invite").json()["token"]
    c.delete(f"/maps/{mid}")
    r = c.get(f"/runs/{rid}/result")
    check("L01", r.status_code in (403, 404, 410), f"삭제 후 result {r.status_code}", f"{r.status_code} {r.text[:120]}")
    _, other = user(); r = other.post(f"/invites/{tok}/accept")
    check("L04", r.status_code in (404, 410), f"삭제된 지도 초대 수락 {r.status_code}", f"{r.status_code} {r.text[:120]}")


def _reset_guest_limiter():
    """IP 시간당 상한(auth.router.guest_join_limiter, 인메모리)을 비운다 — 토큰당 10명 상한(GUEST_LIMIT)과 구분해 보려는 하네스 전용.
    HTTP 모드에서는 서버 메모리에 손댈 수 없어 아무것도 하지 않는다."""
    if BASE_URL:
        return
    from auth.router import guest_join_limiter
    guest_join_limiter._hits.clear()


def l05_l06():
    _reset_guest_limiter()
    uid, c = user(); mid = new_map(c)
    tok = c.post(f"/maps/{mid}/invite").json()["token"]
    if BASE_URL:   # 게스트 11명을 만들려면 IP 시간당 상한을 매번 비워야 한다
        rec("L05.guest11", "SKIP", "IP 시간당 상한을 HTTP로 비울 수 없다 — 로컬 모드에서 본다")
    else:
        anon = client()
        codes = []
        for i in range(11):
            _reset_guest_limiter()   # 토큰당 상한만 보려고 매번 IP 상한을 비운다
            r = anon.post("/auth/guest", json={"display_name": f"게스트{i}", "invite_token": tok}); codes.append(r.status_code)
        check("L05.guest11", codes[:10] == [201] * 10 and codes[10] == 409, "10명 201, 11번째 409 GUEST_LIMIT", f"{codes}")
    _, c2 = user(); mid2 = new_map(c2); tok2 = c2.post(f"/maps/{mid2}/invite").json()["token"]
    _reset_guest_limiter()
    g = client(); gr = g.post("/auth/guest", json={"display_name": "g", "invite_token": tok2})
    if gr.status_code == 201:
        r = g.post("/maps", json={"title": "x", "start_date": "2026-11-10", "end_date": "2026-11-12", "region": SEONGSU})
        check("L06", r.status_code == 403 and r.json().get("code") == "GUEST_NOT_ALLOWED", "게스트 지도 생성 403", f"{r.status_code} {r.text[:100]}")
    else:
        rec("L06", "INFO", f"게스트 생성 불가({gr.status_code}) — 10명 상한 때문일 수 있음")
    c.delete(f"/invites/{tok}")
    _reset_guest_limiter()
    r = client().post("/auth/guest", json={"display_name": "late", "invite_token": tok})
    check("L05.revoked", r.status_code == 410, "폐기 토큰 410", f"{r.status_code} {r.text[:100]}")


def l08():
    uid, c = user(); mid = new_map(c)
    r = c.post("/auth/withdraw")
    check("L08.withdraw", r.status_code == 204, "탈퇴 204", f"{r.status_code} {r.text[:100]}")
    r2 = c.get("/maps")
    check("L08", r2.status_code == 401, "탈퇴 후 같은 쿠키 401", f"{r2.status_code}")
    r3 = c.get(f"/maps/{mid}")
    check("L08.map", r3.status_code in (401, 404), f"탈퇴 후 지도 접근 {r3.status_code}", f"{r3.status_code}")


def s06():
    _, a = user(); _, b = user(); mid = new_map(a)
    for label, r in (("maps", b.get(f"/maps/{mid}")), ("pins", b.get(f"/maps/{mid}/pins")),
                     ("shortlist", b.get(f"/maps/{mid}/shortlist")), ("runs", b.get(f"/maps/{mid}/runs")),
                     ("members", b.get(f"/maps/{mid}/members"))):
        check(f"S06.{label}", r.status_code == 404, "비구성원 404", f"{r.status_code} {r.text[:80]}")


def l02_l03():
    _, a = user(); _, b = user(); mid = new_map(a)
    tok = a.post(f"/maps/{mid}/invite").json()["token"]; b.post(f"/invites/{tok}/accept")
    pin = add_pin(b, mid).json()["id"]
    b.put(f"/pins/{pin}/reaction", json={"type": "like", "reason_text": "좋아요"})
    rid = b.post(f"/maps/{mid}/runs", json={"category": "음식점"}).json()["id"]
    b.post("/auth/withdraw")
    r = b.get(f"/runs/{rid}/result")
    check("L02", r.status_code in (401, 403, 404), f"탈퇴한 요청자 접근 {r.status_code}", f"{r.status_code}")
    check("L02.members", len(a.get(f"/maps/{mid}/members").json()) == 1, "탈퇴자는 구성원에서 빠짐", "구성원 수 불일치")
    pins = a.get(f"/maps/{mid}/pins").json()
    rec("L02.pin_author", "PASS" if pins and pins[0].get("created_by_display_name") == "탈퇴한 구성원" else "FAIL",
        f"탈퇴자 핀 작성자 표기: {pins[0].get('created_by_display_name') if pins else None}")
    # 방장 나가기
    _, o = user(); _, m = user(); omid = new_map(o)
    t2 = o.post(f"/maps/{omid}/invite").json()["token"]; m.post(f"/invites/{t2}/accept")
    r = o.delete(f"/maps/{omid}/members/me")
    rec("L03.owner_leaves_with_member", "PASS" if r.status_code in (204, 409) else "FAIL", f"구성원 있는 방장 나가기 → {r.status_code} {r.text[:80]}")
    _, solo = user(); smid = new_map(solo)
    r = solo.delete(f"/maps/{smid}/members/me")
    rec("L03.owner_alone", "PASS" if r.status_code in (409, 204) else "FAIL", f"혼자인 방장 나가기 → {r.status_code} {r.text[:80]}")


def s03_s05():
    _, a = user(); _, b = user(); mid = new_map(a)
    r = a.get("/me/notifications"); rec("S03.list", "PASS" if r.status_code == 200 else "FAIL", f"{r.status_code}")
    r = a.post("/me/notifications/read", json={"ids": ["00000000-0000-0000-0000-000000000000"]})
    rec("S03.read_unknown", "PASS" if r.status_code in (200, 204, 404, 422) else "FAIL", f"없는 알림 읽음 → {r.status_code}")
    r = a.get(f"/maps/{mid}/shortlist"); check("S05.empty", r.status_code == 200 and r.json() == [], "빈 확정 리스트 200 []", f"{r.status_code} {r.text[:80]}")
    r = a.get(f"/maps/{mid}/shortlist/export"); rec("S05.export_empty", "PASS" if r.status_code in (200, 409, 422) else "FAIL", f"빈 리스트 내보내기 → {r.status_code}")
    for label, body in (("empty", {"message": ""}), ("long", {"message": "가" * 5000}), ("ok", {"message": "좋아요"})):
        r = a.post("/feedback", json=body); rec(f"S04.{label}", "INFO", f"{r.status_code} {r.text[:80]}")


def r3_widen_retry():
    """B05 구성원별 시도 독립 · B06 넓히기 상한 · B07 결과 0 근처 · 재시도 상한과의 관계."""
    _, a = user(); _, b = user(); mid = new_map(a)
    tok = a.post(f"/maps/{mid}/invite").json()["token"]; b.post(f"/invites/{tok}/accept")
    for c in (a, b):
        pid = add_pin(c, mid, skip=0 if c is a else 7).json()["id"]
        c.put(f"/pins/{pid}/reaction", json={"type": "like", "reason_text": "한식이 좋아요"})
    codes_a = [a.post(f"/maps/{mid}/runs", json={"category": "음식점"}).status_code for _ in range(11)]
    r = b.post(f"/maps/{mid}/runs", json={"category": "음식점"})
    check("B05", codes_a[:10] == [202] * 10 and codes_a[10] == 429 and r.status_code == 202,
          "A 10회 후 429, B는 독립적으로 202", f"A {codes_a}, B {r.status_code} {r.text[:100]}")
    rid = r.json()["id"]
    b.post(f"/runs/{rid}/regions/confirm", json={}); b.post(f"/runs/{rid}/execute"); result(b, rid)
    last = None; n = 0
    for _ in range(6):
        last = b.post(f"/runs/{rid}/widen"); n += last.status_code == 202
        if last.status_code == 202:
            result(b, rid)   # 넓히기도 백그라운드로 다시 돈다 — 끝난 뒤에 다음을 누른다
    check("B06", n == 3 and last.status_code == 409 and last.json().get("code") == "WIDEN_LIMIT",
          f"넓히기 3회(15→30분) 후 409 WIDEN_LIMIT", f"{n}회 성공, 마지막 {last.status_code} {last.text[:120]}")


def r3_concurrent_shortlist():
    uid, c = user(); mid = new_map(c); pid = add_pin(c, mid).json()["id"]
    def add(_):
        return client(c.cookies).post(f"/maps/{mid}/shortlist", json={"pin_id": pid}).status_code
    with ThreadPoolExecutor(4) as ex:
        codes = list(ex.map(add, range(4)))
    n = len(c.get(f"/maps/{mid}/shortlist").json())
    check("C05", n == 1 and all(x in (201, 409) for x in codes), f"동시 4요청 → {sorted(codes)}, 항목 {n}개", f"{sorted(codes)}, 항목 {n}개")


def r3_search_edges():
    _, c = user(); mid = new_map(c)
    cases = {"empty": "", "spaces": "   ", "long": "가" * 300, "special": "%_\';--", "emoji": "😋🍜", "single": "a"}
    for k, q in cases.items():
        r = c.get("/places/search", params={"q": q, "lat": 37.5446, "lng": 127.0557, "category": "음식점"})
        # 200이면 결과 수만 남긴다 — 검색 결과(카카오 응답의 이름·좌표)는 기록에 옮기지 않는다(#53)
        note = f"{r.status_code} 결과 {len(r.json())}개" if r.status_code == 200 else f"{r.status_code} {r.text[:80]}"
        rec(f"A15.{k}", "PASS" if r.status_code in (200, 422) else "FAIL", note)


def r3_pin_unsupported_and_dup_ui_codes():
    _, c = user(); mid = new_map(c)
    r1 = add_pin(c, mid); r2 = add_pin(c, mid)
    rec("U05.codes", "PASS" if (r1.status_code, r2.status_code, r2.json().get("code")) == (201, 409, "PIN_DUPLICATE") else "FAIL",
        f"중복 핀 응답 {r2.status_code} {r2.json().get('code')}")


def r3_evidence_enforced():
    """#720: 키 없는 줄(알레르기)은 enforced=false, 키 있는 줄은 true(구현 병합 후 확인 — 필드가 없으면 INFO)."""
    _, c = user(); mid = new_map(c)
    pid = add_pin(c, mid).json()["id"]; pid2 = add_pin(c, mid, skip=2, fact="cuisine_western").json()["id"]
    c.put(f"/pins/{pid}/reaction", json={"type": "like", "reason_text": "한식이 좋아요"})
    c.put(f"/pins/{pid2}/reaction", json={"type": "against", "reason_text": "땅콩 알레르기가 있어서 못 먹어요"})
    rid = c.post(f"/maps/{mid}/runs", json={"category": "음식점"}).json()["id"]
    ev = c.get(f"/runs/{rid}/evidence").json()
    if not any("enforced" in e for e in ev):
        rec("E720", "INFO", "enforced 필드 아직 없음(#720 구현 미병합)"); return
    key = [e for e in ev if e.get("fact_key")]; nokey = [e for e in ev if not e.get("fact_key")]
    check("E720", all(e["enforced"] for e in key) and nokey and all(e["enforced"] is False for e in nokey),
          f"키 있는 줄 {len(key)}개 true, 키 없는 줄 {len(nokey)}개 false", json.dumps(ev, ensure_ascii=False)[:300])


def r3_republish_exclusion():
    """R11: 후보를 지도에 올린 뒤 다시 추천 — 이미 핀이 된 장소는 후보에서 빠진다(가드레일 6)."""
    _, c = user(); mid = new_map(c)
    pid = add_pin(c, mid).json()["id"]
    c.put(f"/pins/{pid}/reaction", json={"type": "like", "reason_text": "한식이 좋아요"})
    def run_once():
        rid = c.post(f"/maps/{mid}/runs", json={"category": "음식점"}).json()["id"]
        c.post(f"/runs/{rid}/regions/confirm", json={}); c.post(f"/runs/{rid}/execute")
        return rid, result(c, rid).json().get("candidates", [])
    rid1, c1 = run_once()
    names1 = [x["place_name"] for x in c1]
    for x in c1:
        c.post(f"/candidates/{x['id']}/publish")
    rid2, c2 = run_once()
    names2 = [x["place_name"] for x in c2]
    check("R11", c1 and c2 and not set(names1) & set(names2), f"1차 {names1} → 2차 {names2} (겹침 없음)",
          f"1차 {names1} → 2차 {names2} (겹침 {set(names1) & set(names2)})")


CASES = {"A01": a01_a02, "A03": a03, "A04": a04_a05, "A06": a06_a09, "A10": a10_a12, "A13": a13_a14, "B01": b01_b03,
         "B04": b04_b08, "C01": c01_c05, "L01": l01_l04, "L05": l05_l06, "L02": l02_l03, "L08": l08, "S03": s03_s05, "S06": s06, "R3a": r3_widen_retry, "R3b": r3_concurrent_shortlist, "R3c": r3_search_edges, "R3d": r3_pin_unsupported_and_dup_ui_codes, "R3e": r3_evidence_enforced, "R3f": r3_republish_exclusion}

if __name__ == "__main__":
    args = sys.argv[1:]
    if "--base-url" in args:
        i = args.index("--base-url")
        BASE_URL = args[i + 1].rstrip("/")
        del args[i:i + 2]
        if not os.environ.get("QA_LOGIN_SECRET"):
            sys.exit("HTTP 모드는 환경 변수 QA_LOGIN_SECRET이 필요하다(스테이징의 값)")
    if not BASE_URL:
        sys.path.insert(0, ".")   # 로컬 모드는 backend 폴더에서 돈다
    want = set(args)
    for name, fn in CASES.items():
        if want and name not in want:
            continue
        try:
            fn()
        except Exception as e:  # noqa: BLE001 — 하네스 오류는 케이스 단위로 격리
            rec(name, "ERR", f"{type(e).__name__}: {str(e)[:200]}")
    count = {v: sum(1 for r in RESULTS if r[1] == v) for v in ("PASS", "FAIL", "SKIP")}
    print(f"\n합계({BASE_URL or '로컬'}): PASS {count['PASS']} / FAIL {count['FAIL']} / SKIP {count['SKIP']}"
          f" / INFO·ERR {len(RESULTS) - sum(count.values())}")
    # CI(staging-check)가 통과 여부를 읽는다 — FAIL이나 하네스 오류(ERR)가 있으면 실패로 끝낸다
    sys.exit(1 if count["FAIL"] or any(r[1] == "ERR" for r in RESULTS) else 0)
