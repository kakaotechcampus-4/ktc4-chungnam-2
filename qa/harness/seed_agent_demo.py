"""「핑고 AI 조언」 시연 지도 만들기(#1301). API만 쓴다 — DB를 직접 쓰지 않고 시각도 조작하지 않는다.

정체(stall)는 「반대 뒤로 다른 카테고리에서 2명이 움직임」(docs/agent-v2.md 6.2 활동 기준, STALL_ACTIVE_MEMBERS)이 바로
성립해 몇 시간을 기다리지 않는다. 갈림(split)은 구성원 모두가 반응하면 바로 성립한다(6.3 all_responded). 그래서 다음
관찰(cron 5분, 또는 `--tick`)에 실제 에이전트가 제안을 낸다. 시연에 보이는 것은 모두 운영 코드가 만든 것이다.

시나리오
- stall(기본): QA 구성원 둘이 음식점 핀 둘에 🚫 사유(칩 + 글)를 남기고, 카페 핀에 ♥를 누른다. 발표자는 초대 링크로 들어와
  보기만 하면 된다. 시트에 지도 현황, 정체 제안, 「핑고가 한 일」, 우리 데이터 줄(라벨이 있으면), 「음식점 추천 받기」가 뜬다.
- split: QA 구성원 둘이 카페 핀 하나에 ♥(「조용해서 좋아요」)와 🚫(「주차가 안 돼서…」)를 남긴다. 발표자가 들어올 때까지
  기다렸다가 멈춘다. **발표자가 그 핀에 ♥를 누르는 순간** 모두 응답한 것이 되어 다음 관찰에 갈림 제안(절충안 수)이 뜬다.

웹 확인 줄(6.8)은 그 장소의 라벨이 「모름」일 때만 생긴다. 라벨은 API로 볼 수 없어 이 스크립트가 고르지 못한다 — 웨이팅처럼
라벨이 비기 쉬운 특징을 사유로 쓴다. 다른 장소를 쓰려면 `--food-query`, `--cafe-query`로 검색어를 바꾼다.

usage (스테이징 — 시크릿이 서버 밖으로 나오지 않게 API 컨테이너 안에서 돌린다, staging-check와 같은 방식):
  cd /srv/pingo/deploy && ./run.sh staging python - --base-url https://staging.ktc-pingopingo.duckdns.org/api --tick < seed_agent_demo.py
  (스크립트를 서버에 올리지 않았으면 curl로 raw 파일을 받아 파이프한다 — docs/demo-guide.md 「핑고 AI 조언 시연」)
usage (로컬 staging 서버):
  PYTHONUTF8=1 QA_LOGIN_SECRET=... python qa/harness/seed_agent_demo.py --base-url http://localhost:8010 [--scenario split]
옵션: --scenario stall|split, --web-url <화면 주소>(기본은 base-url에서 /api를 뗀 것), --wait-join <초>(stall은 기본 0,
split은 기본 900), --tick(끝에 `python -m agent.tick`을 한 번 돌린다 — API 컨테이너 안에서만), --food-query, --cafe-query,
--reason <글>(stall에서 두 번째 🚫의 글을 바꾼다. 1~140자. 따옴표·이모지·긴 글이 깨지지 않는지 보는 QA G04용)
키·시크릿은 출력하지 않는다.
"""
import os
import subprocess
import sys
import time
import uuid
from datetime import date, timedelta

import httpx

SEONGSU = {"label": "성수", "lat": 37.5446, "lng": 127.0557}
OPTS = {"--scenario": "stall", "--web-url": None, "--wait-join": None, "--food-query": "성수 맛집", "--cafe-query": "성수 카페", "--reason": None}
FLAGS = {"--tick": False}

# 사유는 지어낸 예시다. 칩 id는 docs/constraints.md 칩 표의 것이다(food_wait: wait_short, food_spicy: spicy_focused)
STALL_AGAINST = (
    {"reason_chip_ids": ["food_wait"], "reason_text": "웨이팅이 너무 길어서 한 시간 넘게 기다렸어요"},
    {"reason_chip_ids": ["food_spicy"], "reason_text": "너무 매워서 한 입도 못 먹겠어요"},
)
SPLIT_LIKE = {"reason_text": "조용해서 이야기하기 좋아요"}
SPLIT_AGAINST = {"reason_text": "주차가 안 돼서 차로 가기 불편해요"}


def fail(msg: str) -> None:
    sys.exit(f"중단: {msg}")


def ok(r: httpx.Response, what: str, codes=(200, 201, 204)) -> httpx.Response:
    if r.status_code not in codes:
        fail(f"{what} → {r.status_code} {r.text[:200]}")
    return r


def qa_user(base: str, name: str) -> httpx.Client:
    c = httpx.Client(base_url=base, timeout=60)
    r = c.post("/auth/qa-login", headers={"X-QA-Login-Secret": os.environ["QA_LOGIN_SECRET"]},
               json={"display_name": name})
    ok(r, "QA 로그인", (201,))
    return c


def find_place(c: httpx.Client, query: str, category: str, skip: int) -> dict:
    """자체 DB에 짝이 있어 핀을 만들 수 있는(pinnable) 검색 결과의 skip번째. 결과는 이 실행의 메모리에만 둔다(#53)."""
    r = ok(c.get("/places/search", params={"q": query, "lat": SEONGSU["lat"], "lng": SEONGSU["lng"], "limit": 15}), "장소 검색")
    found = [x for x in r.json() if x.get("pinnable", True) and x.get("category") == category]
    if len(found) <= skip:
        fail(f"「{query}」 검색에서 핀을 만들 수 있는 {category}가 {skip + 1}곳보다 적다 — --food-query/--cafe-query로 바꿔 본다")
    return found[skip]


def add_pin(c: httpx.Client, mid: str, place: dict, category: str) -> str:
    body = {"category": category, "place_id": place["place_id"], "place_name": place["place_name"],
            "lat": place["lat"], "lng": place["lng"]}
    return ok(c.post(f"/maps/{mid}/pins", json=body), "핀 만들기").json()["id"]


def react(c: httpx.Client, pin_id: str, kind: str, reason: dict | None = None) -> None:
    ok(c.put(f"/pins/{pin_id}/reaction", json={"type": kind, **(reason or {})}), f"반응({kind})")


def wait_members(c: httpx.Client, mid: str, want: int, seconds: int) -> bool:
    deadline = time.monotonic() + seconds
    while True:
        n = len(ok(c.get(f"/maps/{mid}/members"), "구성원 조회").json())
        if n >= want:
            return True
        if time.monotonic() > deadline:
            return False
        time.sleep(5)


def wait_reactions(c: httpx.Client, pin_id: str, want: int, seconds: int) -> bool:
    deadline = time.monotonic() + seconds
    while True:
        if len(ok(c.get(f"/pins/{pin_id}/reactions"), "반응 조회").json()) >= want:
            return True
        if time.monotonic() > deadline:
            return False
        time.sleep(3)


TICK_TRIES = 8   # tick 한 번은 차례인 지도를 6곳(TICK_MAX_MAPS)만 보고, 새 지도는 차례가 뒤라 몇 번 걸릴 수 있다


def run_tick(c: httpx.Client, mid: str) -> None:
    """이 지도에 제안이 뜰 때까지 `python -m agent.tick`을 돌린다. API 컨테이너 안(또는 backend 폴더)에서만 된다.
    tick은 cron과 같은 명령이라 다른 지도도 같이 관찰한다 — 5분 뒤 cron이 할 일을 앞당길 뿐이다."""
    for n in range(1, TICK_TRIES + 1):
        r = subprocess.run([sys.executable, "-m", "agent.tick"], capture_output=True, text=True)
        if r.returncode != 0:
            print("관찰 tick을 돌리지 못했다(API 컨테이너 밖이면 정상) — 5분 안에 cron이 돌거나 서버에서 "
                  "`./run.sh staging python -m agent.tick`을 돌린다.")
            return
        state = ok(c.get(f"/maps/{mid}/agent"), "에이전트 상태").json()
        if state.get("active_suggestion"):
            print(f"tick {n}번 만에 제안이 떴다: {state['active_suggestion']['title']}")
            return
    print(f"tick {TICK_TRIES}번 동안 제안이 뜨지 않았다 — 다음 cron에서 다시 본다. 원인은 agent_runs의 outcome으로 본다"
          "(docs/demo-guide.md 「핑고 AI 조언 시연」 문제 해결).")


def main() -> None:
    # 컨테이너에서 파이프로 돌면 출력이 끝날 때 한꺼번에 나온다 — 기다리는 동안 초대 링크가 보여야 한다
    sys.stdout.reconfigure(line_buffering=True)
    args = sys.argv[1:]
    if "--base-url" not in args:
        fail("--base-url이 필요하다")
    i = args.index("--base-url")
    base = args[i + 1].rstrip("/")
    del args[i:i + 2]
    for k in list(OPTS):
        if k in args:
            j = args.index(k)
            OPTS[k] = args[j + 1]
            del args[j:j + 2]
    for k in FLAGS:
        if k in args:
            FLAGS[k] = True
            args.remove(k)
    if args:
        fail(f"모르는 인자 {args}")
    if not os.environ.get("QA_LOGIN_SECRET"):
        fail("환경 변수 QA_LOGIN_SECRET이 필요하다(스테이징의 값)")
    scenario = OPTS["--scenario"]
    if scenario not in ("stall", "split"):
        fail("--scenario는 stall 또는 split")
    if OPTS["--reason"] is not None and not 1 <= len(OPTS["--reason"].strip()) <= 140:
        fail("--reason은 1~140자(서버의 사유 길이 상한과 같다)")
    web = (OPTS["--web-url"] or base.removesuffix("/api")).rstrip("/")
    wait = int(OPTS["--wait-join"] or (900 if scenario == "split" else 0))

    tag = uuid.uuid4().hex[:4]
    a = qa_user(base, f"시연 민지 {tag}")
    b = qa_user(base, f"시연 준호 {tag}")
    start = date.today() + timedelta(days=7)
    mid = ok(a.post("/maps", json={
        "title": f"핑고 시연 — 성수 1박 2일 ({'정체' if scenario == 'stall' else '갈림'})",
        "start_date": start.isoformat(), "end_date": (start + timedelta(days=1)).isoformat(), "region": SEONGSU,
    }), "지도 만들기", (201,)).json()["id"]
    token = ok(a.post(f"/maps/{mid}/invite"), "초대 링크").json()["token"]
    ok(b.post(f"/invites/{token}/accept"), "초대 수락")
    invite_url = f"{web}/invites/{token}"

    if scenario == "stall":
        food1 = add_pin(a, mid, find_place(a, OPTS["--food-query"], "음식점", 0), "음식점")
        food2 = add_pin(b, mid, find_place(b, OPTS["--food-query"], "음식점", 1), "음식점")
        cafe = add_pin(a, mid, find_place(a, OPTS["--cafe-query"], "카페", 0), "카페")
        react(a, food2, "against", STALL_AGAINST[0])
        react(b, food1, "against", {**STALL_AGAINST[1], **({"reason_text": OPTS["--reason"]} if OPTS["--reason"] else {})})
        # 반대 뒤로 다른 카테고리에서 두 사람이 움직인다 — 정체의 활동 기준(6.2)
        react(a, cafe, "like")
        react(b, cafe, "like")
        print(f"정체 지도를 만들었다: {mid}")
        print(f"발표자 초대 링크: {invite_url}")
        if wait and not wait_members(a, mid, 3, wait):
            print("발표자가 아직 들어오지 않았다 — 링크로 들어오면 같은 제안이 보인다(제안은 지도 단위다).")
    else:
        cafe = add_pin(a, mid, find_place(a, OPTS["--cafe-query"], "카페", 0), "카페")
        print(f"갈림 지도를 만들었다: {mid}")
        print(f"발표자 초대 링크: {invite_url}  ← 먼저 이 링크로 들어온다({wait}초 기다린다)")
        if not wait_members(a, mid, 3, wait):
            fail("발표자가 들어오지 않았다 — 지도는 남아 있다. 들어온 뒤 --scenario split을 다시 돌리거나 손으로 반응을 남긴다")
        react(a, cafe, "like", SPLIT_LIKE)
        react(b, cafe, "against", SPLIT_AGAINST)
        print("QA 구성원 둘이 카페 핀에 ♥와 🚫를 남겼다. 발표자가 그 카페 핀에 ♥를 누르면 모두 응답한 것이 되어 "
              "다음 관찰에 갈림 제안이 뜬다.")
        if FLAGS["--tick"]:   # 발표자의 ♥를 기다렸다가 돌린다 — 그 전에 돌리면 아직 갈림이 아니다
            if not wait_reactions(a, cafe, 3, wait):
                fail("발표자의 반응이 오지 않았다 — 누른 뒤 서버에서 `./run.sh staging python -m agent.tick`")
    if FLAGS["--tick"]:
        run_tick(a, mid)
    else:
        print("다음 cron tick(5분 안)에 관찰된다. 바로 보려면 서버에서 `./run.sh staging python -m agent.tick`.")


if __name__ == "__main__":
    main()
