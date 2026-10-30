"""모델 호출 비용 측정 시나리오(#870) — BM(크레딧) 설계용. 스테이징(LLM_MODE=real)에서 여행 계획 세 가지를 실제 HTTP로 진행하고,
모델 호출 사용량 기록(llm_calls)을 모아 시나리오·기능별 호출 수, 토큰, 비용 리포트를 낸다.

시나리오(SCENARIOS)
  light  가벼운 여행: 2명, 1박 2일, 의견 차이 적음
  normal 보통 여행: 4명, 2박 3일, 칩과 글 사유 섞임
  split  의견이 갈리는 여행: 6명, 2박 3일, 반대 글 사유 많음, 추천 재시도 여러 번
순서: 지도 생성 → 멤버 참여 → 핀 → 반응·사유 → 추천 실행(「+」 근거, 다시 추천, 새 실행) → 확정 리스트 → AI 코스 짜기 →
진단이 돌 만한 상태(의견 갈림 핀, 반대 뒤 정체)를 남기고 관찰 tick을 기다린다 → 리포트.

모델을 부르는 곳(작업 1 조사)과 이 스크립트가 일으키는 것
  recommend_run  새 추천 실행(POST /maps/{id}/runs)마다 그 카테고리의 글 사유 전부를 ②로(10개씩 묶음). 칩은 모델을 안 거친다
  evidence_add   「+」 근거 추가(PATCH /runs/{id}/evidence)마다 ② 1번
  course         AI 코스 짜기: 요청 글이 있으면 목표 세우기 1 + 목표가 있으면 지휘 턴 최대 5
  agent_diagnose 서버의 관찰 tick(5분)이 의견 갈림·반대 뒤 정체를 찾으면 진단(왕복 최대 6) + 그 안의 ②
  agent_summary  관찰 끝의 우리 조건 요약이 캐시에 없는 글 사유를 ②로
  「다시 추천」(POST /runs/{id}/retry)과 넓히기는 모델을 부르지 않는다.

진단을 기다리는 법
  의견 갈림(전원 응답한 핀에 ♥와 🚫)은 다음 tick(5분 안)에 잡힌다. 반대 뒤 정체는 기준 시간(여행이 가까우면 최소 1시간) 동안
  조용해야 잡힌다. 그래서 기본은 --wait-min(12분)만 기다리고 리포트를 낸 뒤, 끝에 찍는 「다시 리포트」 명령을 1시간 뒤에 돌려
  정체 진단까지 본다. 지도 하루 모델 상한(구성원 수 × 4)이 있어 진단은 지도마다 하루 그 수까지다.

실행(스크립트를 실제로 돌리는 것은 확인 뒤에 한다)
  스테이징 컨테이너 안에서(QA_LOGIN_SECRET과 DATABASE_URL이 컨테이너에 있다. staging-check와 같은 방식):
    cd /srv/pingo/deploy && docker compose exec -T api-staging python - --base-url https://staging.ktc-pingopingo.duckdns.org/api \\
      < /path/to/run_llm_cost.py
    (저장소 파일을 바로 쓰려면 curl -fsSL https://raw.githubusercontent.com/<저장소>/<브랜치>/qa/harness/run_llm_cost.py | docker compose exec -T api-staging python - ...)
  일부만: ... python - --base-url <주소> light normal
  리포트만 다시: ... python - --report light=<map_id>,normal=<map_id>,split=<map_id> --since <ISO 시각>
  로컬(서버를 PINGO_ENV=staging, LLM_MODE=real, AGENT_LOOP_IN_PROCESS=1로 띄운 경우):
    PYTHONUTF8=1 QA_LOGIN_SECRET=... DATABASE_URL=postgresql://pingo:pingo@localhost:5432/pingo_eval python qa/harness/run_llm_cost.py --base-url http://localhost:8000

출력은 마크다운 표다(qa/results/<날짜>-llm-cost.md에 옮겨 적는다). 키·시크릿·사유 원문은 출력하지 않는다(사유는 합성 문장이다).
필요한 것: httpx, sqlalchemy(리포트, 컨테이너에 있다). 비용은 기록 시점 단가로 llm_calls.cost_krw에 이미 계산돼 있다.
"""

import os
import sys
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import httpx

SEONGSU = {"label": "성수", "lat": 37.5446, "lng": 127.0557}
KST = timezone(timedelta(hours=9))
RESULT_WAIT_SEC = 180
COURSE_WAIT_SEC = 240
DEFAULT_WAIT_MIN = 12
FEATURE_ORDER = ("recommend_run", "evidence_add", "course", "agent_diagnose", "agent_summary")
USER_FEATURES = ("recommend_run", "evidence_add", "course")   # 사람이 눌러 생기는 호출. 나머지는 서버(관찰 tick)

# 카테고리마다 성수 근처에서 핀을 만들 수 있는 장소가 나오는 검색어(qa/harness/run_api_cases.py와 같은 동네)
SEARCH_WORDS = {
    "음식점": ("성수 맛집", "성수 한식", "성수 파스타", "성수 고기"),
    "카페": ("성수 카페", "성수 베이커리"),
    "관광지": ("성수 갤러리", "서울숲", "성수 전시"),
}
# 합성 사유. 카테고리마다 순서대로 돌려 쓴다
LIKE_TEXTS = {
    "음식점": ("국물 있는 한식이 좋아요", "고기 구워 먹고 싶어요", "가성비가 좋아 보여요", "분위기 좋아요"),
    "카페": ("조용하고 오래 앉아 있을 수 있어서 좋아요", "디저트가 맛있어 보여요"),
    "관광지": ("사진 찍기 좋아 보여요", "실내라 비 와도 괜찮아요"),
}
AGAINST_TEXTS = {
    "음식점": ("너무 매워 보여요", "웨이팅이 너무 길어요", "양식은 느끼해서 싫어요", "회는 못 먹어요", "너무 비싸요",
              "자리가 좁고 시끄러워요", "주차가 안 돼요", "한식 말고 다른 거 먹고 싶어요"),
    "카페": ("프랜차이즈는 싫어요", "너무 시끄러워요", "좌석이 불편해 보여요"),
    "관광지": ("너무 멀어요", "걷는 게 너무 많아요", "입장료가 비싸요"),
}
EVIDENCE_TEXTS = ("조용한 곳", "주차 되는 곳", "웨이팅 짧은 곳", "아이랑 가기 좋은 곳", "가성비")
COURSE_TEXTS = ("둘째 날은 여유 있게", "둘째 날은 실내 위주로, 덜 걷게", "카페는 마지막에, 첫날은 가볍게")


@dataclass(frozen=True)
class RunSpec:
    member: int                     # 몇 번째 구성원이 누르는지(0 = 방장)
    category: str
    adds: tuple[str, ...] = ()      # 「+」 근거 추가 글(요청 1번에 묶어 보낸다)
    retries: int = 0                # 「다시 추천」 횟수(모델 없음)


@dataclass(frozen=True)
class Scenario:
    name: str
    members: int
    nights: int
    pins: dict                      # 카테고리 → 핀 수
    like_ratio: float               # 반응 중 ♥ 비율(나머지 🚫)
    text_ratio: float               # 사유를 글로 쓰는 비율(나머지는 칩, ♥는 글 아니면 사유 없음)
    split_pins: int                 # 전원이 반응하고 ♥·🚫가 반씩 갈리는 음식점 핀 수(의견 갈림 진단)
    runs: tuple[RunSpec, ...]
    second_round: tuple[RunSpec, ...] = ()   # 사유를 더 남긴 뒤의 새 실행(②가 다시 돈다)
    courses: tuple[tuple[int, str], ...] = ()   # (구성원, 요청 글)
    shortlist: int = 4


SCENARIOS = {
    "light": Scenario(
        "light", members=2, nights=1, pins={"음식점": 3, "카페": 2, "관광지": 2}, like_ratio=0.8, text_ratio=0.3, split_pins=0,
        runs=(RunSpec(0, "음식점"),),
        courses=((0, COURSE_TEXTS[0]),), shortlist=4,
    ),
    "normal": Scenario(
        "normal", members=4, nights=2, pins={"음식점": 5, "카페": 3, "관광지": 3}, like_ratio=0.6, text_ratio=0.5, split_pins=1,
        runs=(RunSpec(0, "음식점", adds=EVIDENCE_TEXTS[:2], retries=1), RunSpec(2, "카페")),
        second_round=(RunSpec(1, "음식점", retries=1),),
        courses=((0, COURSE_TEXTS[1]),), shortlist=6,
    ),
    "split": Scenario(
        "split", members=6, nights=2, pins={"음식점": 6, "카페": 3, "관광지": 3}, like_ratio=0.45, text_ratio=0.8, split_pins=2,
        runs=(RunSpec(0, "음식점", adds=EVIDENCE_TEXTS[:3], retries=2), RunSpec(1, "음식점", retries=2),
              RunSpec(3, "카페", adds=EVIDENCE_TEXTS[3:4], retries=1)),
        second_round=(RunSpec(0, "음식점", retries=1), RunSpec(2, "음식점", adds=EVIDENCE_TEXTS[4:], retries=2),
                      RunSpec(4, "관광지")),
        courses=((0, COURSE_TEXTS[1]), (5, COURSE_TEXTS[2])), shortlist=8,
    ),
}


# ───────── HTTP ─────────

@dataclass
class Member:
    user_id: str
    client: httpx.Client


@dataclass
class Trip:
    scenario: Scenario
    map_id: str = ""
    members: list = field(default_factory=list)
    pins: dict = field(default_factory=lambda: defaultdict(list))   # 카테고리 → [pin_id]
    log: list = field(default_factory=list)                         # 단계별 한 줄(응답 코드만)

    def note(self, text: str) -> None:
        self.log.append(text)
        print(f"[{self.scenario.name}] {text}", flush=True)


def qa_user(base_url: str, tag: str) -> Member:
    c = httpx.Client(base_url=base_url, timeout=60)
    r = c.post("/auth/qa-login", headers={"X-QA-Login-Secret": os.environ["QA_LOGIN_SECRET"]},
               json={"display_name": f"비용측정 {tag}"})
    assert r.status_code == 201, f"QA 로그인 실패 {r.status_code}"
    return Member(r.json()["id"], c)


def search_places(c: httpx.Client, category: str, want: int) -> list[dict]:
    """핀을 만들 수 있는 장소를 이름이 겹치지 않게 want개까지. 결과는 이 실행의 메모리에만 둔다(#53)."""
    found: dict[str, dict] = {}
    for q in SEARCH_WORDS[category]:
        r = c.get("/places/search", params={"q": q, "lat": SEONGSU["lat"], "lng": SEONGSU["lng"], "limit": 15})
        if r.status_code != 200:
            continue
        for x in r.json():
            if x.get("pinnable", True) and x.get("category") == category:
                found.setdefault(x["place_name"], x)
        if len(found) >= want:
            break
    return list(found.values())[:want]


def wait_result(c: httpx.Client, run_id: str) -> int:
    deadline = time.monotonic() + RESULT_WAIT_SEC
    while True:
        r = c.get(f"/runs/{run_id}/result")
        if r.status_code != 409 or r.json().get("code") != "RUN_NOT_FINISHED" or time.monotonic() > deadline:
            return r.status_code
        time.sleep(1)


def setup_map(trip: Trip, base_url: str) -> None:
    s = trip.scenario
    trip.members = [qa_user(base_url, f"{s.name}{i}") for i in range(s.members)]
    owner = trip.members[0].client
    start = datetime.now(KST).date() + timedelta(days=1)   # 여행이 가까울수록 정체 기준 시간이 짧다(최소 1시간)
    r = owner.post("/maps", json={"title": f"비용 측정 {s.name}", "start_date": start.isoformat(),
                                  "end_date": (start + timedelta(days=s.nights)).isoformat(), "region": SEONGSU})
    assert r.status_code == 201, r.text
    trip.map_id = r.json()["id"]
    token = owner.post(f"/maps/{trip.map_id}/invite").json()["token"]
    for m in trip.members[1:]:
        assert m.client.post(f"/invites/{token}/accept").status_code == 200
    trip.note(f"지도 {trip.map_id} 구성원 {s.members}명 {s.nights}박 {s.nights + 1}일")

    for category, n in s.pins.items():
        for i, x in enumerate(search_places(owner, category, n)):
            maker = trip.members[i % len(trip.members)].client
            r = maker.post(f"/maps/{trip.map_id}/pins", json={
                "category": category, "place_id": x["place_id"], "place_name": x["place_name"], "lat": x["lat"], "lng": x["lng"]})
            if r.status_code == 201:
                trip.pins[category].append(r.json()["id"])
        trip.note(f"핀 {category} {len(trip.pins[category])}/{n}")


def react_all(trip: Trip, *, round_no: int) -> None:
    """구성원마다 핀에 반응한다. 비율은 시나리오 값을 결정적으로 따른다(같은 시나리오는 같은 반응). split_pins개의 음식점 핀은
    전원이 반응하고 ♥·🚫가 반씩 갈린다. round_no=1은 두 번째 실행 전에 사유를 더 남기는 단계라 아직 반응하지 않은 칸만 채운다."""
    s = trip.scenario
    chips = {cat: [c["id"] for c in trip.members[0].client.get(f"/categories/{cat}/reason-chips").json()] for cat in s.pins}
    sent = 0
    for category, pin_ids in trip.pins.items():
        for p, pin_id in enumerate(pin_ids):
            split = category == "음식점" and p < s.split_pins
            for i, m in enumerate(trip.members):
                k = p * len(trip.members) + i
                if not split and (k * 7 + round_no) % 10 >= 8:   # 일부 칸은 비워 둔다(전원 응답이 아닌 핀)
                    continue
                if round_no == 1 and (k % 3 != 0 or split):
                    continue
                like = (i % 2 == 0) if split else ((k * 37) % 100) < s.like_ratio * 100
                with_text = split or ((k * 53 + round_no * 11) % 100) < s.text_ratio * 100
                texts = (LIKE_TEXTS if like else AGAINST_TEXTS)[category]
                body: dict = {"type": "like" if like else "against"}
                if with_text:
                    body["reason_text"] = texts[(k + round_no) % len(texts)]
                elif not like:
                    body["reason_chip_ids"] = [chips[category][k % len(chips[category])]]
                sent += m.client.put(f"/pins/{pin_id}/reaction", json=body).status_code == 200
    trip.note(f"반응 {round_no + 1}차 {sent}건")


def run_recommend(trip: Trip, spec: RunSpec) -> None:
    c = trip.members[spec.member].client
    r = c.post(f"/maps/{trip.map_id}/runs", json={"category": spec.category})
    if r.status_code != 202:
        trip.note(f"추천 {spec.category} 구성원{spec.member} → {r.status_code} {r.json().get('code')}")
        return
    run_id = r.json()["id"]
    if spec.adds:
        add = c.patch(f"/runs/{run_id}/evidence", json={"add": [{"text": t} for t in spec.adds]})
        trip.note(f"「+」 {len(spec.adds)}줄 → {add.status_code}")
    c.post(f"/runs/{run_id}/regions/confirm", json={})
    c.post(f"/runs/{run_id}/execute")
    codes = [wait_result(c, run_id)]
    for _ in range(spec.retries):
        retry = c.post(f"/runs/{run_id}/retry")
        codes.append(wait_result(c, run_id) if retry.status_code == 202 else retry.status_code)
    trip.note(f"추천 {spec.category} 구성원{spec.member} 결과 {codes}")


def shortlist_and_course(trip: Trip) -> None:
    s = trip.scenario
    owner = trip.members[0].client
    order = [pid for pids in zip(*[trip.pins[c] for c in trip.pins]) for pid in pids]   # 카테고리를 번갈아
    added = sum(owner.post(f"/maps/{trip.map_id}/shortlist", json={"pin_id": pid}).status_code == 201
                for pid in order[:s.shortlist])
    trip.note(f"확정 리스트 {added}곳")
    for member, text in s.courses:
        c = trip.members[member].client
        r = c.post(f"/maps/{trip.map_id}/courses", json={"request_text": text})
        if r.status_code != 202:
            trip.note(f"코스 구성원{member} → {r.status_code} {r.json().get('code')}")
            continue
        course_id = r.json()["course_run_id"]
        deadline = time.monotonic() + COURSE_WAIT_SEC
        status = "queued"
        while status in ("queued", "running") and time.monotonic() < deadline:
            time.sleep(2)
            status = c.get(f"/course-runs/{course_id}").json().get("status")
        trip.note(f"코스 구성원{member} → {status}")


def leave_stall(trip: Trip) -> None:
    """반대 뒤 정체: 반응이 없던 음식점 핀 하나에 🚫 글을 남기고 조용히 둔다. 기준 시간(최소 1시간)이 지나면 tick이 잡는다."""
    pins = trip.pins.get("음식점") or []
    if pins:
        r = trip.members[-1].client.put(f"/pins/{pins[-1]}/reaction",
                                        json={"type": "against", "reason_text": "여기는 다들 별로라고 할 것 같아요"})
        trip.note(f"정체 신호용 반대 → {r.status_code}")


def play(name: str, base_url: str) -> Trip:
    s = SCENARIOS[name]
    trip = Trip(s)
    setup_map(trip, base_url)
    react_all(trip, round_no=0)
    for spec in s.runs:
        run_recommend(trip, spec)
    if s.second_round:
        react_all(trip, round_no=1)
        for spec in s.second_round:
            run_recommend(trip, spec)
    shortlist_and_course(trip)
    leave_stall(trip)
    return trip


# ───────── 리포트 (llm_calls) ─────────

def load_calls(maps: dict[str, str], since: datetime) -> list[dict]:
    import sqlalchemy as sa

    engine = sa.create_engine(os.environ["DATABASE_URL"])
    try:
        with engine.connect() as conn:
            rows = conn.execute(sa.text(
                "SELECT map_id, feature, call, trace_id, user_id, input_tokens, cached_input_tokens, output_tokens,"
                " cost_krw, ok FROM llm_calls WHERE map_id = ANY(:maps) AND created_at >= :since"
            ), {"maps": list(maps.values()), "since": since}).mappings().all()
    finally:
        engine.dispose()
    by_map = {v: k for k, v in maps.items()}
    return [dict(r, scenario=by_map[r["map_id"]], cost_krw=float(r["cost_krw"])) for r in rows]


def _won(x: float) -> str:
    return f"₩{x:,.3f}"   # 호출 한 번은 1원 미만이다


def _table(head: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join(str(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


def report(calls: list[dict], scenarios: list[str]) -> str:
    out = [f"# 모델 호출 비용 측정 ({datetime.now(KST):%Y-%m-%d %H:%M} KST, 호출 {len(calls)}건)", ""]
    features = [f for f in FEATURE_ORDER if any(c["feature"] == f for c in calls)]

    out += ["## 시나리오별, 기능별", ""]
    rows = []
    for s in scenarios:
        for f in features:
            cs = [c for c in calls if c["scenario"] == s and c["feature"] == f]
            if cs:
                rows.append([s, f, len(cs), len({c["trace_id"] for c in cs}), sum(c["input_tokens"] for c in cs),
                             sum(c["cached_input_tokens"] for c in cs), sum(c["output_tokens"] for c in cs),
                             _won(sum(c["cost_krw"] for c in cs)), sum(not c["ok"] for c in cs)])
    out += [_table(["시나리오", "기능", "호출", "실행", "입력", "캐시 입력", "출력", "비용", "실패"], rows), ""]

    out += ["## 기능별 1회당 비용", "", "호출 = 모델 요청 1번. 실행 = 같은 trace(추천 1번, 「+」 1번, 코스 1번, 진단 1번, 요약 1번).", ""]
    rows = []
    for f in features:
        cs = [c for c in calls if c["feature"] == f]
        traces = defaultdict(float)
        for c in cs:
            traces[c["trace_id"]] += c["cost_krw"]
        per_call = [c["cost_krw"] for c in cs]
        inputs = sum(c["input_tokens"] for c in cs)
        hit = sum(c["cached_input_tokens"] for c in cs) / inputs if inputs else 0
        rows.append([f, len(cs), len(traces), f"{len(cs) / len(traces):.1f}", _won(sum(per_call) / len(cs)), _won(max(per_call)),
                     _won(sum(traces.values()) / len(traces)), _won(max(traces.values())), f"{hit:.0%}"])
    out += [_table(["기능", "호출", "실행", "실행당 호출", "호출 평균", "호출 최대", "실행 평균", "실행 최대", "캐시 비율"], rows), ""]

    out += ["## 시나리오 1건 전체", ""]
    rows = []
    for s in scenarios:
        cs = [c for c in calls if c["scenario"] == s]
        total = sum(c["cost_krw"] for c in cs)
        user = sum(c["cost_krw"] for c in cs if c["feature"] in USER_FEATURES)
        rows.append([s, len(cs), _won(total), _won(user), _won(total - user),
                     f"{user / total:.0%}" if total else "-", f"{(total - user) / total:.0%}" if total else "-"])
    out += [_table(["시나리오", "호출", "전체 비용", "사용자 호출", "서버 호출", "사용자 비중", "서버 비중"], rows), ""]
    out += ["사용자 호출 = recommend_run, evidence_add, course. 서버 호출 = agent_diagnose, agent_summary(관찰 tick).",
            "진단이 0건이면 tick이 아직 돌지 않았거나 신호 기준 시간이 지나지 않은 것이다 — 아래 「다시 리포트」로 다시 본다."]
    return "\n".join(out)


def wait_for_diagnosis(maps: dict[str, str], since: datetime, minutes: int) -> None:
    deadline = time.monotonic() + minutes * 60
    while time.monotonic() < deadline:
        seen = {c["scenario"] for c in load_calls(maps, since) if c["feature"] == "agent_diagnose"}
        print(f"진단 기다리는 중 — 진단이 돈 시나리오 {sorted(seen)} / {sorted(maps)}", flush=True)
        if set(maps) <= seen:
            return
        time.sleep(60)


def main(argv: list[str]) -> int:
    args = list(argv)
    base_url, maps, since, wait_min = None, {}, None, DEFAULT_WAIT_MIN
    if "--report" in args:
        i = args.index("--report")
        maps = dict(pair.split("=", 1) for pair in args[i + 1].split(","))
        del args[i:i + 2]
    if "--since" in args:
        i = args.index("--since")
        since = datetime.fromisoformat(args[i + 1])
        del args[i:i + 2]
    if "--wait-min" in args:
        i = args.index("--wait-min")
        wait_min = int(args[i + 1])
        del args[i:i + 2]
    if "--base-url" in args:
        i = args.index("--base-url")
        base_url = args[i + 1].rstrip("/")
        del args[i:i + 2]

    if maps:   # 리포트만
        if since is None:
            return print("--report에는 --since가 필요하다") or 2
        print(report(load_calls(maps, since), list(maps)))
        return 0
    if not base_url or not os.environ.get("QA_LOGIN_SECRET"):
        return print("--base-url과 환경 변수 QA_LOGIN_SECRET(스테이징의 값)이 필요하다") or 2
    names = args or list(SCENARIOS)
    unknown = [n for n in names if n not in SCENARIOS]
    if unknown:
        return print(f"모르는 시나리오: {unknown} (있는 것: {list(SCENARIOS)})") or 2

    since = datetime.now(timezone.utc) - timedelta(seconds=5)
    trips = {name: play(name, base_url) for name in names}
    maps = {name: t.map_id for name, t in trips.items()}
    rerun = f"--report {','.join(f'{k}={v}' for k, v in maps.items())} --since {since.isoformat()}"
    if not os.environ.get("DATABASE_URL"):
        print(f"DATABASE_URL이 없어 리포트를 건너뛴다. DB에 닿는 곳에서: python run_llm_cost.py {rerun}")
        return 0
    if wait_min > 0:
        wait_for_diagnosis(maps, since, wait_min)
    print(report(load_calls(maps, since), names))
    print(f"\n다시 리포트(1시간 뒤 정체 진단까지): python - {rerun}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
