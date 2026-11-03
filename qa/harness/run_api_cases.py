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
import queue
import sys
import threading
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
        c.put(f"/pins/{pin}/reaction", json={"type": "like"})   # 사유 글이 없으면 ② 호출이 없다 — 31번 돌려도 모델 비용 0
    codes = []
    for i in range(31):
        cat = ("음식점", "카페", "관광지")[i % 3]
        r = c.post(f"/maps/{mid}/runs", json={"category": cat}); codes.append(r.status_code)
    last = r
    d = last.json().get("detail") or {}
    check("B04", codes[:30] == [202] * 30 and codes[30] == 402 and last.json().get("code") == "CREDIT_INSUFFICIENT"
          and d.get("required") == 1 and d.get("balance") == 0,
          "30회까지 202, 31번째 402 CREDIT_INSUFFICIENT(required 1, balance 0)", f"{codes} {last.text[:150]}")
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


def p01():
    """비구성원 404를 id가 든 경로 전부에서(#1096, docs/permissions.md 「비구성원 vs 권한 없음」). 본문은 유효하게 보낸다 —
    422가 404보다 먼저 나오면 권한을 본 게 아니다. 지우는 요청은 맨 뒤에 두고, 끝나고 A의 데이터가 그대로인지 본다.
    404는 앱 오류 본문(code)이 있어야 통과다 — 경로가 없을 때의 404({"detail": "Not Found"})를 권한으로 세지 않는다.
    핀 휴지통(GET /maps/{id}/trash, POST /pins/{id}/restore)은 서버 구현 전이라 넣지 않았다(#864, 생기면 넣는다)."""
    _, a = user(); _, b = user(); mid = new_map(a)
    pin = add_pin(a, mid).json()["id"]; pin2 = add_pin(a, mid, skip=1).json()["id"]
    a.put(f"/pins/{pin}/reaction", json={"type": "like"})   # 사유 글 없이 — ② 호출 없음
    review = a.put(f"/pins/{pin}/reviews/me", json={"rating": 4, "body": "QA 후기"}).json()["review"]["id"]
    item = a.post(f"/maps/{mid}/shortlist", json={"pin_id": pin}).json()["id"]
    tok = a.post(f"/maps/{mid}/invite").json()["token"]
    rid = a.post(f"/maps/{mid}/runs", json={"category": "음식점", "execute": True}).json()["id"]
    cands = (result(a, rid).json() or {}).get("candidates") or []
    _, lat, lng, _ = place()
    body_pin = {"category": "음식점", "place_id": "hint", "place_name": "QA", "lat": lat, "lng": lng}
    calls = [
        ("GET", f"/maps/{mid}", None), ("PATCH", f"/maps/{mid}", {"title": "남의 지도"}),
        ("POST", f"/maps/{mid}/owner", {"user_id": "x"}), ("POST", f"/maps/{mid}/invite", None),
        ("GET", f"/maps/{mid}/invites", None), ("DELETE", f"/invites/{tok}", None),
        ("GET", f"/maps/{mid}/members", None), ("GET", f"/maps/{mid}/pins", None), ("POST", f"/maps/{mid}/pins", body_pin),
        ("POST", f"/maps/{mid}/pins/link-preview", {"urls": ["https://map.kakao.com/"]}),
        ("POST", f"/maps/{mid}/pins/bulk", {"pins": [body_pin]}), ("GET", f"/maps/{mid}/counts", None),
        ("PATCH", f"/pins/{pin}", {"memo": "남의 핀"}),
        ("POST", f"/pins/{pin}/resolve", {"place_name": "QA", "lat": lat, "lng": lng}),
        ("GET", f"/pins/{pin}/reviews", None), ("PUT", f"/pins/{pin}/reviews/me", {"rating": 1, "body": "남의 지도 후기"}),
        ("POST", f"/reviews/{review}/reports", None),
        ("PUT", f"/pins/{pin}/reaction", {"type": "like"}), ("GET", f"/pins/{pin}/reactions", None),
        ("GET", f"/maps/{mid}/recommend/readiness", None), ("GET", f"/maps/{mid}/runs", None),
        ("POST", f"/maps/{mid}/runs", {"category": "음식점"}),
        *[("POST", f"/candidates/{x['id']}/publish", None) for x in cands[:1]],   # 다시 추천이 후보를 바꾸기 전에
        ("GET", f"/runs/{rid}/evidence", None), ("PATCH", f"/runs/{rid}/evidence", {"add": [{"text": "조용한 곳"}]}),
        ("POST", f"/runs/{rid}/regions/confirm", {}), ("POST", f"/runs/{rid}/execute", None),
        ("GET", f"/runs/{rid}/result", None), ("POST", f"/runs/{rid}/widen", None), ("POST", f"/runs/{rid}/retry", None),
        ("GET", f"/runs/{rid}/advice", None),
        ("GET", f"/maps/{mid}/shortlist", None), ("POST", f"/maps/{mid}/shortlist", {"pin_id": pin2}),
        ("GET", f"/maps/{mid}/shortlist/export", None), ("PUT", f"/maps/{mid}/shortlist/order", {"item_ids": [item]}),
        ("GET", f"/maps/{mid}/route", None), ("POST", f"/maps/{mid}/route", None),
        ("GET", f"/maps/{mid}/ads?lat={lat}&lng={lng}", None),
        ("GET", f"/maps/{mid}/agent", None), ("PUT", f"/maps/{mid}/agent/settings", {"enabled": False}),
        ("POST", f"/maps/{mid}/courses", {"request_text": "QA"}), ("GET", f"/maps/{mid}/courses/latest", None),
        # 지우는 요청은 마지막
        ("DELETE", f"/pins/{pin}/reaction", None), ("DELETE", f"/pins/{pin}/reviews/me", None),
        ("DELETE", f"/shortlist/{item}", None), ("DELETE", f"/pins/{pin2}", None),
        ("DELETE", f"/maps/{mid}/members/me", None), ("POST", f"/maps/{mid}/restore", None), ("DELETE", f"/maps/{mid}", None),
    ]
    bad = []
    for method, path, body in calls:
        r = b.request(method, path, json=body) if body is not None else b.request(method, path)
        if r.status_code != 404 or "code" not in r.json():
            bad.append(f"{method} {path.replace(mid, '{map}').replace(pin2, '{pin2}').replace(pin, '{pin}').replace(rid, '{run}')} → {r.status_code} {r.text[:40] if r.status_code == 404 else ''}")
    check("P01", not bad, f"비구성원 {len(calls)}개 요청 모두 404" + ("" if cands else " (후보 0곳 — publish 빠짐)"),
          f"404가 아닌 {len(bad)}/{len(calls)}개: " + "; ".join(bad))
    pins_after = {p["id"] for p in a.get(f"/maps/{mid}/pins").json()}
    me = (a.get(f"/pins/{pin}/reviews").json() or {}).get("mine")
    kept = a.get(f"/maps/{mid}").status_code == 200 and {pin, pin2} <= pins_after and me and len(a.get(f"/maps/{mid}/shortlist").json()) == 1
    check("P01.kept", bool(kept), "A의 지도·핀·후기·확정 리스트 그대로", f"지도/핀/후기/확정 중 바뀐 것 있음: 핀 {len(pins_after)}, 후기 {bool(me)}")


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


def r3_widen_retry():
    """B05 구성원별 크레딧 독립 · B06 넓히기 상한 · B07 결과 0 근처."""
    _, a = user(); _, b = user(); mid = new_map(a)
    tok = a.post(f"/maps/{mid}/invite").json()["token"]; b.post(f"/invites/{tok}/accept")
    pa = add_pin(a, mid).json()["id"]
    pb = add_pin(b, mid, skip=7).json()["id"]
    a.put(f"/pins/{pa}/reaction", json={"type": "like"})   # A는 사유 글 없이 — 30번 돌려도 ② 호출이 없다
    codes_a = [a.post(f"/maps/{mid}/runs", json={"category": "음식점"}).status_code for _ in range(31)]
    b.put(f"/pins/{pb}/reaction", json={"type": "like", "reason_text": "한식이 좋아요"})   # B06의 결과용, ② 1번
    r = b.post(f"/maps/{mid}/runs", json={"category": "음식점"})
    check("B05", codes_a[:30] == [202] * 30 and codes_a[30] == 402 and r.status_code == 202,
          "A 30회 후 402, B는 자기 크레딧으로 202", f"A {codes_a}, B {r.status_code} {r.text[:100]}")
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


# ───────── 크레딧 원장(W, #1091) — docs/credits-reviews.md 3·5절 ─────────
# 숫자(처음 값, 상한, 가격, 보상)는 적지 않고 GET /credits/me에서 받는다. ♥는 사유 글 없이 남겨 ② 호출이 없다.
BUSAN = {"label": "부산", "lat": 35.1796, "lng": 129.0756}
_W_USERS: list = []   # W07이 잔액 = 원장 합을 볼 계정


def _credits(c):
    return c.get("/credits/me").json()


def _review(c, pin, body="QA 후기"):
    return c.put(f"/pins/{pin}/reviews/me", json={"rating": 4, "body": body})


def w01_w07():
    uid, c = user(); _W_USERS.append(uid); mid = new_map(c)
    r = c.get("/credits/me"); me = r.json()
    cap, reward, price = me.get("max_balance"), me.get("review_reward"), (me.get("prices") or {}).get("recommend_run")
    check("W01", r.status_code == 200 and me.get("balance") == cap and all(isinstance(v, int) and v > 0 for v in (cap, reward, price))
          and (me.get("prices") or {}).get("course", 0) > 0,
          f"처음 잔액 = 상한 {cap}, 추천 {price}, 보상 {reward}", f"{r.status_code} {r.text[:150]}")

    p1 = add_pin(c, mid).json()["id"]; p2 = add_pin(c, mid, skip=1).json()["id"]
    c.put(f"/pins/{p1}/reaction", json={"type": "like"})
    first = _review(c, p1).json()
    c.delete(f"/pins/{p1}/reviews/me")

    k = max(1, reward // 2)   # 상한 바로 아래로 내려 보상이 상한까지만 채우는지 본다(30 → 25, 보상 10 → +5)
    codes = [c.post(f"/maps/{mid}/runs", json={"category": "음식점"}).status_code for _ in range(k)]
    bal = _credits(c)["balance"]
    again = _review(c, p1).json()
    check("W02", first.get("credited") == 0 and first.get("balance") == cap and again.get("credited") == 0 and again.get("balance") == bal,
          "상한에서 후기 0, 지웠다 다시 써도 0", f"처음 {first}, 다시 {again} (그 전 잔액 {bal})")

    new = _review(c, p2).json(); edit = _review(c, p2, "QA 후기 고침").json()
    want = min(reward, cap - bal)
    check("W03", codes == [202] * k and bal == cap - k * price and new.get("credited") == want and new.get("balance") == bal + want
          and edit.get("credited") == 0 and edit.get("balance") == bal + want,
          f"{k}번 추천 뒤 {bal}에서 새 장소 후기 +{want}, 고치기 0", f"추천 {codes}, 잔액 {bal}, 새 후기 {new}, 고치기 {edit}")

    before = _credits(c)["balance"]; key = uuid.uuid4().hex
    r1 = c.post(f"/maps/{mid}/runs", json={"category": "음식점"}, headers={"Idempotency-Key": key})
    r2 = c.post(f"/maps/{mid}/runs", json={"category": "음식점"}, headers={"Idempotency-Key": key})
    after = _credits(c)["balance"]
    check("W04", r1.status_code == 202 and r2.is_success and r1.json().get("id") == r2.json().get("id") and after == before - price,
          f"같은 키 두 번 → 같은 run, {price}만 빠짐", f"{r1.status_code}/{r2.status_code} 같은 run {r1.json().get('id') == r2.json().get('id')}, 잔액 {before} → {after}")

    # 0곳: 여행 지역이 부산인 지도에 서울 핀 — 후보는 여행 지역과 같은 시·도만이라(#1055) 첫 실행이 0곳이다
    uid2, z = user(); _W_USERS.append(uid2); zmid = new_map(z, region=BUSAN)
    zp = add_pin(z, zmid).json()["id"]; z.put(f"/pins/{zp}/reaction", json={"type": "like"})
    b0 = _credits(z)["balance"]
    run = z.post(f"/maps/{zmid}/runs", json={"category": "음식점", "execute": True})
    rid = run.json().get("id"); res = result(z, rid) if rid else run
    b1 = _credits(z)["balance"]
    zero = res.status_code == 404 and res.json().get("code") == "NO_RESULTS"
    if not zero:
        rec("W05", "INFO", f"0곳을 만들지 못함(결과 {res.status_code}) — 부산 지도·서울 핀 전제가 바뀌었는지 본다")
    else:
        rt = z.post(f"/runs/{rid}/retry"); result(z, rid); b2 = _credits(z)["balance"]
        wd = z.post(f"/runs/{rid}/widen"); result(z, rid); b3 = _credits(z)["balance"]
        check("W05", run.status_code == rt.status_code == wd.status_code == 202 and b0 == b1 == b2 == b3,   # 거절된 요청은 잔액이 그대로여도 본 게 아니다
              f"첫 실행 0곳 차감 없음, 다시 추천({rt.status_code})·넓히기({wd.status_code})도 0", f"잔액 {b0} → {b1} → {b2} → {b3}")

    _reset_guest_limiter()
    tok = c.post(f"/maps/{mid}/invite").json()["token"]
    g = client(); gr = g.post("/auth/guest", json={"display_name": "QA 게스트", "invite_token": tok})
    if gr.status_code != 201:
        rec("W06", "INFO", f"게스트를 만들지 못함({gr.status_code}) — 게스트 상한 때문일 수 있음")
    else:
        gm = g.get("/credits/me"); gr2 = g.post(f"/maps/{mid}/runs", json={"category": "음식점"})
        ok = all(x.status_code == 403 and x.json().get("code") == "GUEST_NOT_ALLOWED"
                 and (x.json().get("detail") or {}).get("initial_credits") == cap for x in (gm, gr2))
        check("W06", ok, f"게스트 /credits/me·추천 403 GUEST_NOT_ALLOWED, initial_credits {cap}",
              f"/credits/me {gm.status_code} {gm.text[:100]}, 추천 {gr2.status_code} {gr2.text[:100]}")

    if BASE_URL:
        rec("W07", "SKIP", "원장은 API로 볼 수 없다 — 로컬 모드에서 본다")
        return
    import sqlalchemy as sa
    from common import database
    with database.SessionLocal() as db:
        rows = db.execute(sa.text("""select a.user_id, a.balance, coalesce(sum(l.delta), 0) from credit_accounts a
            left join credit_ledger l on l.user_id = a.user_id where a.user_id = any(:ids) group by a.user_id, a.balance"""),
            {"ids": _W_USERS}).all()
    bad = [r for r in rows if r[1] != r[2]]
    check("W07", len(rows) == len(_W_USERS) and not bad, f"계정 {len(rows)}개 잔액 = 원장 합", f"계정 {len(rows)}/{len(_W_USERS)}, 어긋남 {bad}")


# ───────── 남은 HTTP 케이스(#1114) — 숫자는 응답에서 받고, ♥는 사유 글 없이 남긴다(② 호출 없음) ─────────
def _zero_run():
    """0곳 run — 부산 지도에 서울 핀(W05와 같은 전제). (client, run_id, 결과 응답)"""
    _, z = user(); zmid = new_map(z, region=BUSAN)
    zp = add_pin(z, zmid).json()["id"]; z.put(f"/pins/{zp}/reaction", json={"type": "like"})
    rid = z.post(f"/maps/{zmid}/runs", json={"category": "음식점", "execute": True}).json().get("id")
    return z, rid, result(z, rid)


def _no_results(r):
    return r.status_code == 404 and r.json().get("code") == "NO_RESULTS" and "funnel" in (r.json().get("detail") or {})


def b07():
    z, rid, res = _zero_run()
    if not _no_results(res):
        rec("B07", "INFO", f"0곳을 만들지 못함({res.status_code} {res.text[:80]}) — 부산 지도·서울 핀 전제가 바뀌었는지 본다"); return
    b0 = _credits(z)["balance"]; out = []
    for step in ("widen", "retry"):
        r = z.post(f"/runs/{rid}/{step}"); res = result(z, rid)
        out.append((step, r.status_code, _no_results(res)))
    b1 = _credits(z)["balance"]
    check("B07", all(s == 202 and ok for _, s, ok in out) and b0 == b1,
          "넓히기·다시 추천 202, 결과는 여전히 NO_RESULTS(funnel 있음), 잔액 그대로", f"{out}, 잔액 {b0} → {b1}")


def c02():
    _, c = user(); mid = new_map(c); pin = add_pin(c, mid).json()["id"]
    c.put(f"/pins/{pin}/reaction", json={"type": "like"})
    price = _credits(c)["prices"]["recommend_run"]
    def post(key):
        h = {"Idempotency-Key": key} if key else {}
        return client(c.cookies).post(f"/maps/{mid}/runs", json={"category": "음식점"}, headers=h)
    b0 = _credits(c)["balance"]
    with ThreadPoolExecutor(2) as ex:
        rs = list(ex.map(post, [None, None]))
    b1 = _credits(c)["balance"]
    check("C02.nokey", [r.status_code for r in rs] == [202, 202] and b0 - b1 == 2 * price,
          f"키 없이 동시 2번 → 202 둘, {2 * price} 빠짐", f"{[(r.status_code, r.text[:60]) for r in rs]}, 잔액 {b0} → {b1}")
    key = uuid.uuid4().hex
    with ThreadPoolExecutor(2) as ex:
        rs = list(ex.map(post, [key, key]))
    # 같은 키 동시 요청은 하나가 처리 중이라 409 REQUEST_IN_PROGRESS를 받을 수 있다 — 그 뒤 같은 키로 다시 부르면 같은 run이다
    ok = [r for r in rs if r.is_success]
    busy = [r for r in rs if r.status_code == 409 and r.json().get("code") == "REQUEST_IN_PROGRESS"]
    again = post(key)
    b2 = _credits(c)["balance"]
    ids = {r.json().get("id") for r in ok + [again] if r.is_success}
    check("C02.key", ok and len(ok) + len(busy) == 2 and again.is_success and len(ids) == 1 and b1 - b2 == price,
          f"같은 키 동시 2번 → 202와 처리 중 409만, 다시 부르면 같은 run, {price}만 빠짐",
          f"{[(r.status_code, r.text[:60]) for r in rs]}, 재요청 {again.status_code}, run {len(ids)}개, 잔액 {b1} → {b2}")


def _wait_course(c, cid):
    deadline = time.monotonic() + 120
    while True:
        r = c.get(f"/course-runs/{cid}")
        if r.json().get("status") in ("done", "failed") or time.monotonic() > deadline:
            return r
        time.sleep(2)


def _two_shortlisted(c, mid, skips=(0, 1)):
    for skip in skips:
        pid = add_pin(c, mid, skip=skip).json()["id"]
        c.post(f"/maps/{mid}/shortlist", json={"pin_id": pid})


def w08_s07():
    _, c = user(); mid = new_map(c)
    price = _credits(c)["prices"]["course"]
    # 핀 1개 → 422, 잔액 그대로
    p0 = add_pin(c, mid).json()["id"]; c.post(f"/maps/{mid}/shortlist", json={"pin_id": p0})
    b0 = _credits(c)["balance"]
    r = c.post(f"/maps/{mid}/courses", json={})
    check("W08.422", r.status_code == 422 and r.json().get("code") == "COURSE_NOT_ENOUGH_PLACES" and _credits(c)["balance"] == b0,
          "확정 1곳 422 COURSE_NOT_ENOUGH_PLACES, 잔액 그대로", f"{r.status_code} {r.text[:100]}")
    p1 = add_pin(c, mid, skip=1).json()["id"]; c.post(f"/maps/{mid}/shortlist", json={"pin_id": p1})
    # S07 — 방장과 게스트. 게스트는 IP 시간당 상한(W06·L05와 합쳐 10명 안쪽)이라 1명만 만든다
    _reset_guest_limiter()
    tok = c.post(f"/maps/{mid}/invite").json()["token"]
    g = client(); gr = g.post("/auth/guest", json={"display_name": "QA 게스트", "invite_token": tok})
    if gr.status_code != 201:
        rec("S07", "INFO", f"게스트를 만들지 못함({gr.status_code})")
    else:
        ms = c.get(f"/maps/{mid}/members").json()
        check("S07", len(ms) == 2 and sorted(m.get("is_guest") for m in ms) == [False, True] and all("is_guest" in m for m in ms),
              "구성원 2명, 방장 is_guest false·게스트 true", f"{[(m.get('role'), m.get('is_guest')) for m in ms]}")
        r = g.post(f"/maps/{mid}/courses", json={})
        check("W08.guest", r.status_code == 403 and r.json().get("code") == "GUEST_NOT_ALLOWED", "게스트 코스 403 GUEST_NOT_ALLOWED", f"{r.status_code} {r.text[:100]}")
    # 2곳 → 202, 진행 중에 또 부르면 409(run이 빨리 끝났으면 새 run 202), 끝난 run마다 done=차감 / failed=환불
    r = c.post(f"/maps/{mid}/courses", json={})
    if r.status_code != 202:
        rec("W08", "FAIL", f"코스 요청 {r.status_code} {r.text[:120]}"); return
    ids = [r.json()["course_run_id"]]
    again = c.post(f"/maps/{mid}/courses", json={})
    if again.status_code == 202:   # 로컬 TestClient는 응답 전에 끝난다
        ids.append(again.json()["course_run_id"])
    runs = [_wait_course(c, i).json() for i in ids]; b1 = _credits(c)["balance"]
    sts = [x.get("status") for x in runs]
    busy = again.status_code == 409 and again.json().get("code") == "COURSE_IN_PROGRESS"
    if not busy:
        rec("W08.409", "SKIP" if again.status_code == 202 else "FAIL", f"진행 중 재요청 {again.status_code} — run이 이미 끝났다")
    check("W08", all(x in ("done", "failed") for x in sts) and b1 == b0 - price * sts.count("done"),
          f"{sts} → done마다 −{price}, failed는 환불", f"{sts} {[x.get('failure_code') for x in runs]}, 잔액 {b0} → {b1}")


def w09():
    _, c = user(); mid = new_map(c)
    pin = add_pin(c, mid).json()["id"]; c.put(f"/pins/{pin}/reaction", json={"type": "like"})
    me = _credits(c); price = me["prices"]["recommend_run"]
    for _ in range(me["balance"] // price):
        c.post(f"/maps/{mid}/runs", json={"category": "음식점"})
    _two_shortlisted(c, mid, (1, 2))   # 0번 장소는 ♥ 핀으로 이미 있다
    r = c.post(f"/maps/{mid}/courses", json={}); d = r.json().get("detail") or {}
    latest = c.get(f"/maps/{mid}/courses/latest")
    check("W09", r.status_code == 402 and r.json().get("code") == "CREDIT_INSUFFICIENT" and d.get("required") == me["prices"]["course"]
          and d.get("balance") == 0 and latest.status_code == 204,
          "잔액 0 코스 402 CREDIT_INSUFFICIENT(required=course 가격, balance 0), run 안 남음(204)", f"{r.status_code} {r.text[:120]}, latest {latest.status_code}")


def c06():
    _, a = user(); mid = new_map(a); pin = add_pin(a, mid).json()["id"]
    a.put(f"/pins/{pin}/reaction", json={"type": "like"})
    a.post(f"/maps/{mid}/runs", json={"category": "음식점"})   # 새 계정은 잔액이 상한이라 보상이 0 — 1번 써서 상한 아래로 내린다(♥ 글 없음)
    me = _credits(a); before = me["balance"]
    want = min(me["review_reward"], me["max_balance"] - before)
    def put(_):
        return client(a.cookies).put(f"/pins/{pin}/reviews/me", json={"rating": 4, "body": "QA 동시 후기"})
    with ThreadPoolExecutor(2) as ex:
        rs = list(ex.map(put, range(2)))
    mine = [x for x in a.get(f"/pins/{pin}/reviews").json().get("items", []) if x.get("is_mine")]
    got = sum((r.json().get("credited") or 0) for r in rs if r.status_code == 200); after = _credits(a)["balance"]
    check("C06.put", want > 0 and all(r.status_code == 200 for r in rs) and len(mine) == 1 and got == want and after == before + want,
          f"동시 2번 저장 → 후기 1개, 보상 합 {got} = {want}, 잔액 {before} → {after}",
          f"{[(r.status_code, r.text[:80]) for r in rs]}, 후기 {len(mine)}개, 보상 합 {got}/기대 {want}, 잔액 {before} → {after}")
    rid = next(r.json()["review"]["id"] for r in rs if r.status_code == 200)
    _, b = user(); bmid = new_map(b); add_pin(b, bmid)   # 같은 장소를 가리키는 핀이 있는 다른 지도의 구성원
    def rep(_):
        return client(b.cookies).post(f"/reviews/{rid}/reports")
    with ThreadPoolExecutor(2) as ex:
        rs = list(ex.map(rep, range(2)))
    check("C06.report", [r.status_code for r in rs] == [204, 204], "같은 후기 신고 동시 2번 → 204 둘", f"{[(r.status_code, r.text[:80]) for r in rs]}")
    r = a.post(f"/reviews/{rid}/reports")
    check("C06.self", r.status_code == 422, "내 후기 신고 422", f"{r.status_code} {r.text[:100]}")
    _reset_guest_limiter()
    tok = a.post(f"/maps/{mid}/invite").json()["token"]
    g = client(); gr = g.post("/auth/guest", json={"display_name": "QA 게스트", "invite_token": tok})
    if gr.status_code != 201:
        rec("C06.guest", "INFO", f"게스트를 만들지 못함({gr.status_code})"); return
    r = g.post(f"/reviews/{rid}/reports")
    check("C06.guest", r.status_code == 403 and r.json().get("code") == "GUEST_NOT_ALLOWED", "게스트 신고 403 GUEST_NOT_ALLOWED", f"{r.status_code} {r.text[:100]}")


def _until_429(c, send, limit=40):
    """429가 처음 나오는 번째(1부터)와 그 전의 코드 모음. 상한 값은 서버 설정이라 시험에 적지 않는다."""
    codes = []
    for _ in range(limit):
        r = send(); codes.append(r.status_code)
        if r.status_code == 429:
            return len(codes), codes, r
    return None, codes, r


def s04():
    _, a = user()
    cases = {"empty": {"message": ""}, "spaces": {"message": "   "}, "1001": {"message": "가" * 1001},
             "extra": {"message": "좋아요", "nope": 1}}
    bad = {k: a.post("/feedback", json=b).status_code for k, b in cases.items()}
    ok1000 = a.post("/feedback", json={"message": "가" * 1000}).status_code
    check("S04.edge", all(v == 422 for v in bad.values()) and ok1000 == 201, "빈 글·공백·1001자·모르는 필드 422, 1000자 201", f"{bad}, 1000자 {ok1000}")
    _, b = user()
    n, codes, r = _until_429(b, lambda: b.post("/feedback", json={"message": "QA 피드백"}))
    check("S04.limit", n is not None and n > 1 and set(codes[:-1]) == {201} and r.json().get("code") == "RATE_LIMITED",
          f"{n - 1 if n else '?'}건까지 201, 다음은 429 RATE_LIMITED", f"{codes[-5:]} {r.text[:100]}")


def b09():
    _, c = user()
    n, codes, r = _until_429(c, lambda: c.get("/places/search", params={"q": "카페", "lat": SEONGSU["lat"], "lng": SEONGSU["lng"]}))
    # ponytail: 상한은 인스턴스 메모리라 스테이징이 한 대라는 전제다 — 여러 대면 40번 안에 못 볼 수 있다
    check("B09", n is not None and n > 1 and set(codes[:-1]) <= {200, 503} and r.json().get("code") == "RATE_LIMITED",
          f"{n - 1 if n else '?'}번까지 통과, 다음은 429 RATE_LIMITED", f"{codes[-5:]} {r.text[:100]}")


# ───────── 계정 수명·코스 환불·로그(#1125) — DB와 서버 함수를 직접 써서 로컬 전용이다. HTTP(스테이징)는 SKIP ─────────
def _local_only(cid):
    if BASE_URL:
        rec(cid, "SKIP", "DB·서버 함수가 필요하다 — 로컬 모드에서 본다")
    return bool(BASE_URL)


def _sql(q, **p):
    import sqlalchemy as sa
    from common import database
    with database.SessionLocal() as db:
        return db.execute(sa.text(q), p).all()


def _count(q, **p):
    return _sql(q, **p)[0][0]


def _withdraw_case(uid, c, with_data=True):
    """탈퇴 전에 실제로 데이터가 있는 계정: 혼자 방장인 지도 + 핀 + 잔액을 30이 아닌 값(추천 3번)으로. (mid, 핀 수, 잔액)"""
    mid = new_map(c); pin = add_pin(c, mid).json()["id"]
    c.put(f"/pins/{pin}/reaction", json={"type": "like"})
    for _ in range(3):
        c.post(f"/maps/{mid}/runs", json={"category": "음식점"})
    return mid, len(c.get(f"/maps/{mid}/pins").json()), _credits(c)["balance"]


def _pending_client(uid):
    import time
    from auth import core
    from auth.service import WithdrawnAccountPending, find_or_create_user
    from common import database
    from common.settings import settings
    with database.SessionLocal() as db:
        try:
            find_or_create_user(db, provider="kakao", provider_user_id=f"test_{uid}", display_name="x")
            return None, "예외 없음(탈퇴 계정이 안 걸렸다)"
        except WithdrawnAccountPending as e:
            val = core.create_pending_cookie_value(e.user.id, e.provider, e.user.deleted_at, secret=settings.session_secret,
                                                   issued_at=int(time.time()))
    return client({"pending_account": val}), ""


def l09():
    if _local_only("L09"):
        return
    # 되살리기: 지도·핀·잔액이 탈퇴 전 값과 같다
    uid, c = user(); mid, pins0, bal0 = _withdraw_case(uid, c)
    cap = _credits(c)["max_balance"]
    if not (pins0 == 1 and bal0 < cap):
        rec("L09", "FAIL", f"전제 실패 — 핀 {pins0}개, 잔액 {bal0}/{cap}"); return
    w = c.post("/auth/withdraw"); gone = c.get("/auth/me")
    pc, why = _pending_client(uid)
    if pc is None:
        rec("L09", "FAIL", why); return
    pend = pc.get("/auth/pending"); r = pc.post("/auth/pending", json={"choice": "restore"})
    ok = w.status_code == 204 and gone.status_code == 401 and pend.status_code == 200 and r.status_code == 200 and r.json().get("id") == uid
    m = pc.get(f"/maps/{mid}"); pins1 = len(pc.get(f"/maps/{mid}/pins").json()) if m.status_code == 200 else -1
    bal1 = _credits(pc)["balance"] if r.status_code == 200 else -1
    check("L09.restore", ok and m.status_code == 200 and pins1 == pins0 and bal1 == bal0,
          f"탈퇴 204·세션 무효 401 → 되살리기 200, 지도·핀 {pins0}개·잔액 {bal0} 그대로",
          f"withdraw {w.status_code}, me {gone.status_code}, pending {pend.status_code}, restore {r.status_code} {r.text[:80]}, 지도 {m.status_code}, 핀 {pins1}/{pins0}, 잔액 {bal1}/{bal0}")
    # 새로 시작: 새 계정에 잔액은 처음 값, 옛 계정은 지워진다
    uid2, c2 = user(); _, _, bal2 = _withdraw_case(uid2, c2)
    c2.post("/auth/withdraw"); pc2, why = _pending_client(uid2)
    if pc2 is None:
        rec("L09.restart", "FAIL", why); return
    r = pc2.post("/auth/pending", json={"choice": "restart"})
    new = r.json().get("id") if r.status_code == 201 else None
    bal3 = _credits(pc2)["balance"] if new else -1
    old_rows = _count("select count(*) from credit_accounts where user_id=:u", u=uid2)
    check("L09.restart", r.status_code == 201 and new and new != uid2 and bal2 < cap and bal3 == cap and old_rows == 0 and not pc2.get("/maps").json().get("items", pc2.get("/maps").json()),
          f"새로 시작 201, 새 계정 잔액 {cap}(전 {bal2}), 옛 크레딧 계정 삭제, 지도 없음",
          f"{r.status_code} {r.text[:80]}, 잔액 {bal3}/{cap}(전 {bal2}), 옛 계정 행 {old_rows}")


def l10():
    if _local_only("L10"):
        return
    from datetime import datetime, timedelta, timezone
    from auth import api as auth_api
    from common import database
    xid, x = user(); uid, m = user(); mid = new_map(x)
    m.post(f"/invites/{x.post(f'/maps/{mid}/invite').json()['token']}/accept")
    pin = add_pin(m, mid).json()["id"]
    m.put(f"/pins/{pin}/reaction", json={"type": "like"}); m.post(f"/maps/{mid}/runs", json={"category": "음식점"})
    _review(m, pin)
    name = m.get("/auth/me").json()["display_name"]
    q = lambda t: _count(f"select count(*) from {t} where user_id=:u", u=uid)
    before = dict(acc=q("credit_accounts"), led=q("credit_ledger"), rev=q("reviews"), ident=_count("select count(*) from user_identities where user_id=:u", u=uid))
    notified = name in str(x.get("/me/notifications").json())
    if not (before["acc"] and before["led"] and before["rev"] and before["ident"]):
        rec("L10", "FAIL", f"전제 실패 — {before}"); return
    w = m.post("/auth/withdraw")
    with database.SessionLocal() as db:
        n_early = auth_api.purge_withdrawn_accounts(db, datetime.now(timezone.utc)); db.commit()   # 7일 전에는 정리되지 않는다
    early = q("credit_accounts")
    with database.SessionLocal() as db:
        n = auth_api.purge_withdrawn_accounts(db, datetime.now(timezone.utc) + timedelta(days=8)); db.commit()
    after = dict(acc=q("credit_accounts"), led=q("credit_ledger"), rev=q("reviews"),
                 ident=_count("select count(*) from user_identities where user_id=:u", u=uid))
    shown = _sql("select display_name from users where id=:u", u=uid)[0][0]
    pins = x.get(f"/maps/{mid}/pins").json(); who = [p.get("created_by_display_name") for p in pins if p["id"] == pin]
    check("L10", w.status_code == 204 and early == before["acc"] and n >= 1 and after["acc"] == 0 and after["led"] == 0
          and after["rev"] == before["rev"] and after["ident"] == 0 and shown == "탈퇴한 구성원" and who == ["탈퇴한 구성원"],
          "7일 전엔 그대로, 8일 뒤 크레딧 계정·원장·로그인 수단 삭제, 후기는 남음, 이름 「탈퇴한 구성원」(users, 핀 작성자)",
          f"withdraw {w.status_code}, 전 {before}, 이른 정리 뒤 계정 {early}, 정리 {n}, 후 {after}, 이름 {shown}, 핀 작성자 {who}")
    if not notified:
        rec("L10.notify", "INFO", "방장 알림에 이름이 복사되지 않아 알림 비식별화는 못 봄")
    else:
        check("L10.notify", name not in str(x.get("/me/notifications").json()), "정리 뒤 방장 알림에 이름이 없다", "알림에 이름이 남아 있다")


def l07():
    if _local_only("L07"):
        return
    from auth.service import claim_guest
    from common import database
    oid, o = user(); mid = new_map(o); tok = o.post(f"/maps/{mid}/invite").json()["token"]
    mid_user, mc = user()   # 카카오 수단이 있는 정식 사용자 M
    _reset_guest_limiter()
    g = client(); gr = g.post("/auth/guest", json={"display_name": "QA 게스트", "invite_token": tok})
    if gr.status_code != 201:
        rec("L07", "FAIL", f"게스트 생성 {gr.status_code}"); return
    gid = gr.json().get("user", gr.json()).get("id") or g.get("/auth/me").json()["id"]
    pin = add_pin(g, mid).json()["id"]; g.put(f"/pins/{pin}/reaction", json={"type": "like"})
    st = lambda: dict(pin=_count("select count(*) from pins where id=:p and created_by=:u", p=pin, u=mid_user),
                      react=_count("select count(*) from reactions where pin_id=:p and user_id=:u", p=pin, u=mid_user),
                      member=_count("select count(*) from memberships where map_id=:m and user_id=:u", m=mid, u=mid_user))
    before = st()
    gdel = lambda: _sql("select deleted_at from users where id=:u", u=gid)[0][0]
    if any(before.values()) or gdel() is not None or _count("select count(*) from pins where id=:p and created_by=:g", p=pin, g=gid) != 1:
        rec("L07", "FAIL", f"전제 실패 — 합치기 전에 이미 M의 것: {before}"); return
    def claim():
        with database.SessionLocal() as db:
            out = claim_guest(db, guest_user_id=gid, provider="kakao", provider_user_id=f"test_{mid_user}", display_name="QA 카카오")
            db.commit()
            return out[0].id, out[1]
    first = claim(); a1 = st(); d1 = gdel(); second = claim(); a2 = st()
    check("L07", first == (mid_user, True) and a1 == dict(pin=1, react=1, member=1) and d1 is not None and a2 == a1 and second[0] == mid_user and second[1] is None,
          "핀·반응·구성원 자격이 M으로, 게스트 deleted_at, 다시 불러도 그대로(None)", f"첫 {first}, 뒤 {a1}, 게스트 지움 {d1}, 다시 {second} {a2}")


def w10():
    if _local_only("W10"):
        return
    from agent.course.gateways import get_opening_hours_gateway
    uid, c = user(); mid = new_map(c); _two_shortlisted(c, mid)
    led = lambda r: _count("select count(*) from credit_ledger where user_id=:u and reason=:r", u=uid, r=r)
    class Boom:
        def get_opening_hours(self, place_ids):
            raise RuntimeError("boom")
    app = _app(); b0 = _credits(c)["balance"]
    app.dependency_overrides[get_opening_hours_gateway] = lambda: Boom()
    try:
        r = c.post(f"/maps/{mid}/courses", json={}); cid = r.json().get("course_run_id")
    finally:
        app.dependency_overrides.pop(get_opening_hours_gateway, None)
    run = c.get(f"/course-runs/{cid}").json() if cid else {}
    c.get(f"/course-runs/{cid}"); b1 = _credits(c)["balance"]
    check("W10.engine", r.status_code == 202 and (run.get("status"), run.get("failure_code")) == ("failed", "ENGINE_ERROR")
          and b1 == b0 and led("spend") == 1 and led("refund") == 1,
          "엔진 실패 → failed ENGINE_ERROR, 잔액 그대로, 원장 차감 1·환불 1(GET 두 번 뒤에도)", f"{r.status_code} {run.get('status')} {run.get('failure_code')}, 잔액 {b0} → {b1}, 원장 차감 {led('spend')} 환불 {led('refund')}")
    # 두 번째 run은 정상으로 끝낸 뒤 「15분 넘게 진행 중」으로 되돌려 INTERRUPTED 환불을 본다 — 환불이 아직 없던 run이라 증거가 된다
    r = c.post(f"/maps/{mid}/courses", json={}); cid2 = r.json().get("course_run_id")
    done = c.get(f"/course-runs/{cid2}").json().get("status") if cid2 else None
    b2 = _credits(c)["balance"]
    import sqlalchemy as sa
    from common import database
    with database.SessionLocal() as db:
        db.execute(sa.text("update agent_course_runs set status='running', failure_code=null, finished_at=null, created_at=now()-interval '16 minutes' where id=:i"), {"i": cid2})
        db.commit()
    got = c.get(f"/course-runs/{cid2}").json(); c.get(f"/course-runs/{cid2}"); b3 = _credits(c)["balance"]
    check("W10.interrupted", done == "done" and (got.get("status"), got.get("failure_code")) == ("failed", "INTERRUPTED")
          and b3 == b2 + _credits(c)["prices"]["course"] and led("refund") == 2 and led("spend") == 2,
          "오래 진행 중인 run → INTERRUPTED, 환불 한 번(GET 두 번), 원장 차감 2·환불 2", f"처음 {done}, 뒤 {got.get('status')} {got.get('failure_code')}, 잔액 {b2} → {b3}, 원장 차감 {led('spend')} 환불 {led('refund')}")


def g01():
    if _local_only("LOG01"):
        return
    import logging
    secret = f"QA_SECRET_{uuid.uuid4().hex}"; probe = f"QA_PROBE_{uuid.uuid4().hex}"
    seen = []
    class Grab(logging.Handler):
        def emit(self, rec_):
            seen.append(" ".join([rec_.getMessage(), str(rec_.args), rec_.exc_text or "", str(rec_.exc_info[1]) if rec_.exc_info else ""]))
    root = logging.getLogger(); h = Grab(); old = root.level; quiet = list(root.handlers)
    for x in quiet:
        x.setLevel(logging.WARNING)   # 화면에는 DEBUG를 찍지 않는다(잡기만 한다)
    root.addHandler(h); root.setLevel(logging.DEBUG)
    try:
        logging.getLogger("qa.probe").info("probe %s", probe)   # 이 장치가 로그를 실제로 잡는지 — 못 잡으면 빈 통과다
        _, c = user(); mid = new_map(c); pin = add_pin(c, mid).json()["id"]; pin2 = add_pin(c, mid, skip=1).json()["id"]
        sent = [c.put(f"/pins/{pin}/reaction", json={"type": "like", "reason_text": f"한식이 좋아요 {secret}"}),
                c.put(f"/pins/{pin2}/reaction", json={"type": "against", "reason_text": f"별로예요 {secret}"}),
                _review(c, pin, f"후기 {secret}"), c.get("/places/search", params={"q": secret}),
                c.post("/feedback", json={"message": f"피드백 {secret}"})]
        rid = c.post(f"/maps/{mid}/runs", json={"category": "음식점", "execute": True}).json().get("id")
        if rid:
            result(c, rid)
    finally:
        root.removeHandler(h); root.setLevel(old)
        for x in quiet:
            x.setLevel(logging.NOTSET)
    ok_codes = [r.status_code for r in sent]
    caught = any(probe in t for t in seen); leaks = [t[:80] for t in seen if secret in t]
    check("LOG01", caught and all(x in (200, 201) for x in ok_codes) and not leaks,
          f"로그 {len(seen)}줄에 사유·후기·검색어·피드백 원문 없음(요청 {ok_codes})",
          f"장치가 로그를 잡음 {caught}, 요청 {ok_codes}, 새어 나간 로그 {len(leaks)}줄 {leaks[:2]}")


# ───────── 실시간 SSE(#1158) — HTTP 전용. 끝없는 스트림은 로컬 TestClient에 약하고 로컬은 realtime 단위 테스트가 덮는다 ─────────
SSE_LINE_WAIT = 10   # 다음 줄을 기다리는 시간(초). 넘으면 그 케이스는 FAIL — 무한 대기 없음(매일 06시 점검)
SSE_CASE_MAX = 30    # 케이스 하나의 최대 시간(초)


class _Sse:
    """SSE 구독 하나. 스레드가 httpx stream을 읽어 큐에 넣는다. 항목: ("status", 코드), ("ev", {id,event,data}), ("eof",), ("err", 클래스명)."""

    def __init__(self, c, path, headers=None):
        self.q = queue.Queue()
        self.resp = None
        self.cl = client(c.cookies)
        threading.Thread(target=self._run, args=(path, headers or {}), daemon=True).start()

    def _run(self, path, headers):
        try:
            with self.cl.stream("GET", path, headers=headers) as r:
                self.resp = r
                self.q.put(("status", r.status_code))
                if r.status_code == 200:
                    ev = {}
                    for line in r.iter_lines():
                        if line == "":
                            if ev:
                                self.q.put(("ev", ev)); ev = {}
                        elif not line.startswith(":") and ":" in line:
                            k, v = line.split(":", 1); ev[k] = v.lstrip(" ")
            self.q.put(("eof",))
        except Exception as e:  # noqa: BLE001 — 우리가 close()한 경우도 여기로 온다
            self.q.put(("err", type(e).__name__))

    def get(self, dl, wait=SSE_LINE_WAIT):
        """다음 항목. 줄 타임아웃이나 케이스 시간이 다 되면 None."""
        try:
            return self.q.get(timeout=max(0.1, min(wait, dl - time.monotonic())))
        except queue.Empty:
            return None

    def close(self):
        if self.resp is not None:
            try:
                self.resp.close()
            except Exception:  # noqa: BLE001
                pass


def _sse_open(s, dl):
    """(상태 코드, 첫 데이터가 control ping인가)."""
    st = s.get(dl)
    if not st or st[0] != "status":
        return None, False
    if st[1] != 200:
        return st[1], False
    e = s.get(dl)
    return 200, bool(e and e[0] == "ev" and e[1].get("event") == "control" and json.loads(e[1]["data"]).get("type") == "ping")


def _sse_event(s, dl, wait=SSE_LINE_WAIT):
    """control이 아닌 다음 이벤트(dict). 스트림이 끝났으면 "eof", 시간 초과면 None."""
    while True:
        it = s.get(dl, wait)
        if it is None:
            return None
        if it[0] != "ev":
            return "eof"
        if it[1].get("event") != "control":
            return it[1]


def _sse_drain(s, dl):
    """스트림이 닫힐 때까지의 이벤트들과 끝 모양("eof" | None=시간 초과)."""
    evs = []
    while True:
        e = _sse_event(s, dl)
        if not isinstance(e, dict):
            return evs, e
        evs.append(e)


def _sse_ready(s, cid, dl):
    """구독을 열고 200 + ping을 확인한다. 구독 등록이 첫 ping 뒤라 잠깐 기다린다(ping 직후 이벤트를 놓치지 않게)."""
    st, ping = _sse_open(s, dl)
    check(f"{cid}.open", st == 200 and ping, "200, 첫 데이터 control ping", f"{st}, ping {ping}")
    time.sleep(1)
    return st == 200 and ping


def s01():
    if not BASE_URL:
        rec("S01", "SKIP", "끝없는 스트림은 HTTP에서만 본다 — 로컬은 realtime 단위 테스트가 덮는다"); return
    dl = time.monotonic() + SSE_CASE_MAX
    _, a = user(); mid = new_map(a); path = f"/maps/{mid}/events"
    s = _Sse(a, path)
    if not _sse_ready(s, "S01", dl):
        s.close(); return
    p1 = add_pin(a, mid, 0).json()["id"]
    e = _sse_event(s, dl); s.close()
    live = isinstance(e, dict) and e.get("event") == "pin.created" and json.loads(e["data"]).get("id") == p1 and e.get("id", "").isdigit()
    check("S01.live", live, f"구독 중 핀 → pin.created 받음(id {e.get('id') if live else ''})", f"받은 것 {e}")
    if not live:
        return
    last = e["id"]
    # 끊긴 동안 실제로 이벤트가 생겼는지부터 확인한다 — 안 생겼으면 「놓친 이벤트를 받았다」는 빈 통과다
    added = [add_pin(a, mid, k) for k in (1, 2)]
    ids = [r.json().get("id") for r in added]
    have = [p["id"] for p in a.get(f"/maps/{mid}/pins").json()]
    made = all(r.status_code == 201 for r in added) and all(i in have for i in ids) and p1 in have
    check("S01.missed_made", made, "끊긴 동안 핀 2개가 실제로 생김", f"{[r.status_code for r in added]}, 지도 핀 {len(have)}개")
    if not made:
        return
    s2 = _Sse(a, path, {"Last-Event-ID": last})
    st, ping = _sse_open(s2, dl)
    got = []
    while st == 200 and len(got) < 2:
        x = _sse_event(s2, dl)
        if not isinstance(x, dict):
            break
        got.append(x)
    s2.close()
    seqs = [int(x["id"]) if x.get("id", "").isdigit() else -1 for x in got]
    ok = (len(got) == 2 and [x.get("event") for x in got] == ["pin.created"] * 2
          and [json.loads(x["data"]).get("id") for x in got] == ids and seqs[0] > int(last) and seqs[0] < seqs[1])
    check("S01.replay", ok, f"놓친 핀 2개가 순서대로 다시 옴(id {seqs}, 기록한 id {last} 뒤)",
          f"상태 {st}, ping {ping}, 받은 것 {[(x.get('id'), x.get('event')) for x in got]}, 기대 핀 {ids}")
    # 숫자가 아닌 Last-Event-ID는 무시하고 지금부터 받는다 — 앞의 핀 3개가 다시 오면 안 된다
    s3 = _Sse(a, path, {"Last-Event-ID": "abc"})
    if not _sse_ready(s3, "S01.bad_id", dl):
        s3.close(); return
    p4 = add_pin(a, mid, 3).json()["id"]
    # 폴러가 구멍을 기다리며 앞 이벤트(2792·2793)를 늦게 내보낼 수 있다 — 그건 재전송이 아니라서 새 핀이 올 때까지 읽고,
    # 기록한 id 이하(처음부터 재전송하면 오는 것)가 오지 않았는지 본다. ponytail: 직전 두 핀만 다시 보내는 서버는 못 거른다
    seen = []
    while True:
        x = _sse_event(s3, dl)
        if not isinstance(x, dict):
            break
        seen.append(x)
        if x.get("event") == "pin.created" and json.loads(x["data"]).get("id") == p4:
            break
    s3.close()
    old = [x.get("id") for x in seen if x.get("id", "").isdigit() and int(x["id"]) <= int(last)]
    got4 = bool(seen) and seen[-1].get("event") == "pin.created" and json.loads(seen[-1]["data"]).get("id") == p4
    check("S01.bad_id", got4 and not old, f"숫자가 아닌 Last-Event-ID는 무시 — 기록한 id {last} 이하 재전송 없이 새 핀을 받음",
          f"새 핀 받음 {got4}, 기록한 id 이하로 온 것 {old}, 받은 것 {[x.get('id') for x in seen]}")


def s02():
    if not BASE_URL:
        rec("S02", "SKIP", "끝없는 스트림은 HTTP에서만 본다 — 로컬은 realtime 단위 테스트(test_close_on_leave)가 덮는다"); return
    dl = time.monotonic() + SSE_CASE_MAX
    # (c) 비구성원은 404
    _, a = user(); _, n = user(); mid = new_map(a)
    s = _Sse(n, f"/maps/{mid}/events"); st = s.get(dl); s.close()
    check("S02.nonmember", st == ("status", 404), "비구성원 구독 404", f"{st}")

    def joined(owner, mid):
        uid, b = user(); tok = owner.post(f"/maps/{mid}/invite").json()["token"]
        assert b.post(f"/invites/{tok}/accept").status_code in (200, 201), "초대 수락 실패"
        return uid, b

    # (a) 구성원이 나가면 그 구독만 닫힌다
    buid, b = joined(a, mid)
    sa, sb = _Sse(a, f"/maps/{mid}/events"), _Sse(b, f"/maps/{mid}/events")
    if not (_sse_ready(sa, "S02.leave_a", dl) and _sse_ready(sb, "S02.leave_b", dl)):
        sa.close(); sb.close(); return
    r = b.delete(f"/maps/{mid}/members/me")
    evs, end = _sse_drain(sb, dl)
    check("S02.leave_closed", r.status_code == 204 and end == "eof", f"나간 사람의 구독이 닫힘(받은 이벤트 {[e.get('event') for e in evs]})",
          f"나가기 {r.status_code}, 끝 모양 {end}(None=닫히지 않음), 이벤트 {[e.get('event') for e in evs]}")
    e = _sse_event(sa, dl)
    while isinstance(e, dict) and e.get("event") != "member.left":   # 초대 수락의 member.joined가 늦게 올 수 있다
        e = _sse_event(sa, dl)
    left = isinstance(e, dict) and json.loads(e["data"]).get("user_id") == buid
    after = sa.get(dl, 2)   # 남은 구성원의 구독은 열려 있다 — 2초 동안 닫힘(eof/err)이 없어야 한다
    check("S02.leave_others_stay", left and (after is None or after[0] == "ev"), "남은 구성원은 member.left를 받고 구독이 그대로", f"받은 것 {e}, 이어서 {after}")
    sa.close()
    s = _Sse(b, f"/maps/{mid}/events"); st = s.get(dl); s.close()
    check("S02.leave_resub", st == ("status", 404), "나간 사람의 재구독 404", f"{st}")

    # (b) 방장이 지도를 지우면 구독자 모두 map.deleted를 받고 닫힌다
    _, a2 = user(); mid2 = new_map(a2); _, b2 = joined(a2, mid2)
    subs = {"owner": (a2, _Sse(a2, f"/maps/{mid2}/events")), "member": (b2, _Sse(b2, f"/maps/{mid2}/events"))}
    if not all(_sse_ready(s, f"S02.del_{k}", dl) for k, (_, s) in subs.items()):
        for _, s in subs.values():
            s.close()
        return
    r = a2.delete(f"/maps/{mid2}")
    check("S02.delete", r.status_code == 204, "지도 삭제 204", f"{r.status_code}")
    for k, (cl, s) in subs.items():
        evs, end = _sse_drain(s, dl); s.close()
        names = [e.get("event") for e in evs]
        deleted = [e for e in evs if e.get("event") == "map.deleted" and json.loads(e["data"]).get("map_id") == mid2]
        check(f"S02.del_{k}", bool(deleted) and end == "eof" and names[-1] == "map.deleted",
              f"{k}: map.deleted를 받은 뒤 닫힘", f"{k}: 이벤트 {names}, 끝 모양 {end}(None=닫히지 않음)")
        s2 = _Sse(cl, f"/maps/{mid2}/events"); st = s2.get(dl); s2.close()
        check(f"S02.del_{k}_resub", st == ("status", 404), f"{k}: 삭제된 지도 재구독 404", f"{st}")


CASES = {"A01": a01_a02, "A03": a03, "A04": a04_a05, "A06": a06_a09, "A10": a10_a12, "A13": a13_a14, "B01": b01_b03,
         "B04": b04_b08, "C01": c01_c05, "L01": l01_l04, "L05": l05_l06, "L02": l02_l03, "L08": l08, "S03": s03_s05, "S06": s06, "R3a": r3_widen_retry, "R3b": r3_concurrent_shortlist, "R3c": r3_search_edges, "R3d": r3_pin_unsupported_and_dup_ui_codes, "R3e": r3_evidence_enforced, "R3f": r3_republish_exclusion, "W01": w01_w07}

CASES["P01"] = p01   # 사전 밖에 둔다 — 다른 PR이 사전 줄을 같이 고쳐도 충돌하지 않게
for _k, _f in (("B07", b07), ("C02", c02), ("W08", w08_s07), ("W09", w09), ("C06", c06), ("S04", s04), ("B09", b09)):
    CASES[_k] = _f
for _k, _f in (("S01", s01), ("S02", s02)):
    CASES[_k] = _f
for _k, _f in (("L07", l07), ("L09", l09), ("L10", l10), ("W10", w10), ("LOG01", g01)):
    CASES[_k] = _f

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
