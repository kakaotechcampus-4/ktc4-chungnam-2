import { afterAll, beforeAll, afterEach, describe, expect, it } from "vitest";
import { server } from "./node";
import { resetScenario } from "./scenarios";
import { store } from "./store";

const BASE = "https://api.pingo.example.com";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => resetScenario("happy-path"));
afterAll(() => server.close());

describe("기획안 6절 핵심 시나리오 — happy path", () => {
  it("로그인 → 핀 목록 → 반응 → 추천 준비 → run → 근거 → 지역확인 → 실행 → 결과 → 게시 → 확정 → 동선", async () => {
    // 로그인
    const me = await fetch(`${BASE}/auth/me`).then((r) => r.json());
    expect(me.id).toBe("u_me");

    // 핀 목록 (시드된 3개)
    const pins = await fetch(`${BASE}/maps/map_1/pins`).then((r) => r.json());
    expect(pins.length).toBe(3);

    // 반응 등록 (반대는 사유 필수 — 실패 케이스)
    const badReaction = await fetch(`${BASE}/pins/pin_1/reaction`, {
      method: "PUT",
      body: JSON.stringify({ type: "against" }),
    });
    expect(badReaction.status).toBe(422);
    const badBody = await badReaction.json();
    expect(badBody.code).toBe("EVIDENCE_REQUIRED");

    // 추천 준비 판정 — 음식점은 이미 시드에서 임계값 충족
    const readiness = await fetch(`${BASE}/maps/map_1/recommend/readiness`).then((r) => r.json());
    expect(readiness["음식점"].ready).toBe(true);

    // run 생성
    const run = await fetch(`${BASE}/maps/map_1/runs`, {
      method: "POST",
      body: JSON.stringify({ category: "음식점" }),
    }).then((r) => r.json());
    expect(run.status).toBe("collecting_evidence");

    // 근거 리스트
    const evidence = await fetch(`${BASE}/runs/${run.id}/evidence`).then((r) => r.json());
    expect(evidence.length).toBeGreaterThan(0);
    expect(evidence[0].permissions.can_disable).toBe(true); // 내가 쓴 것
    // #228 — 방향: wants=false는 "제외", true는 "선호", 키 없는 줄은 둘 다 없다
    const excluded = evidence.find((e: { fact_key: string }) => e.fact_key === "cuisine_korean");
    expect(excluded.wants).toBe(false);
    expect(excluded.fact_label).toBe("한식");
    expect(evidence.find((e: { fact_key: string }) => e.fact_key === "cuisine_raw_fish").wants).toBe(true);
    const plain = evidence.find((e: { fact_key: string | null }) => e.fact_key === null);
    expect(plain.wants).toBeUndefined();

    // 지역 확인
    const regionsRes = await fetch(`${BASE}/runs/${run.id}/regions/confirm`, { method: "POST", body: "{}" });
    expect(regionsRes.status).toBe(200);

    // 실행
    const execRes = await fetch(`${BASE}/runs/${run.id}/execute`, { method: "POST" });
    expect(execRes.status).toBe(202);

    // 결과 — 후보 3곳, 전부 비공개
    const result = await fetch(`${BASE}/runs/${run.id}/result`).then((r) => r.json());
    expect(result.candidates.length).toBe(3);
    expect(result.candidates[0].visibility).toBe("private");

    // 아직 게시 전이므로 다른 사람에게는 안 보인다 (visibility=private, source_run_id로 판정)
    const pinsBeforePublish = await fetch(`${BASE}/maps/map_1/pins`).then((r) => r.json());
    expect(pinsBeforePublish.length).toBe(3);

    // 게시
    const publishedPin = await fetch(`${BASE}/candidates/${result.candidates[0].id}/publish`, { method: "POST" }).then((r) => r.json());
    expect(publishedPin.kind).toBe("AI추천");
    expect(publishedPin.visibility).toBe("public");
    expect(publishedPin.checks.length).toBeGreaterThan(0); // 가드레일 5: 근거가 게시 후에도 유지

    const pinsAfterPublish = await fetch(`${BASE}/maps/map_1/pins`).then((r) => r.json());
    expect(pinsAfterPublish.length).toBe(4);

    // 확정 리스트에 추가
    const item = await fetch(`${BASE}/maps/map_1/shortlist`, {
      method: "POST",
      body: JSON.stringify({ pin_id: publishedPin.id }),
    }).then((r) => r.json());
    expect(item.pin.kind).toBe("확정");

    // 두 번째 핀도 확정에 추가해서 동선 확인
    const item2 = await fetch(`${BASE}/maps/map_1/shortlist`, {
      method: "POST",
      body: JSON.stringify({ pin_id: "pin_1" }),
    }).then((r) => r.json());
    expect(item2.pin.kind).toBe("확정");

    // #30: GET은 마지막 계산 결과만 준다 — 확정 리스트가 바뀌어도 자동 재계산하지 않는다
    const beforeCalc = await fetch(`${BASE}/maps/map_1/route`).then((r) => r.json());
    expect(beforeCalc.length).toBe(0);

    // 「동선 짜주기」를 눌러야 계산된다
    const routes = await fetch(`${BASE}/maps/map_1/route`, { method: "POST" }).then((r) => r.json());
    expect(routes.length).toBe(1);
    expect(routes[0].legs.length).toBe(1);

    const afterCalc = await fetch(`${BASE}/maps/map_1/route`).then((r) => r.json());
    expect(afterCalc.length).toBe(1);

    // 수동 정렬(#30) — 순서를 뒤집어도 동선과는 무관
    const shortlistItems = await fetch(`${BASE}/maps/map_1/shortlist`).then((r) => r.json());
    const reordered = await fetch(`${BASE}/maps/map_1/shortlist/order`, {
      method: "PUT",
      body: JSON.stringify({ item_ids: shortlistItems.map((i: any) => i.id).reverse() }),
    }).then((r) => r.json());
    expect(reordered[0].id).toBe(shortlistItems[1].id);
  });
});

describe("에러 시나리오", () => {
  it("no-results — 결과 0개는 404 NO_RESULTS", async () => {
    resetScenario("no-results");
    const res = await fetch(`${BASE}/runs/run_no_results/result`);
    expect(res.status).toBe(404);
    const body = await res.json();
    expect(body.code).toBe("NO_RESULTS");
    expect(body.detail.funnel.length).toBeGreaterThan(0);
  });

  it("retry-limit — 5회 초과 시 429 RETRY_LIMIT", async () => {
    resetScenario("retry-limit");
    const res = await fetch(`${BASE}/runs/run_retry_limit/retry`, { method: "POST" });
    expect(res.status).toBe(429);
    const body = await res.json();
    expect(body.code).toBe("RETRY_LIMIT");
  });

  it("region-conflict — 확인 없이 confirm하면 409 REGION_CONFLICT", async () => {
    resetScenario("region-conflict");
    const res = await fetch(`${BASE}/runs/run_region_conflict/regions/confirm`, { method: "POST", body: "{}" });
    expect(res.status).toBe(409);
    const body = await res.json();
    expect(body.code).toBe("REGION_CONFLICT");

    const res2 = await fetch(`${BASE}/runs/run_region_conflict/regions/confirm`, {
      method: "POST",
      body: JSON.stringify({ accept_union: true }),
    });
    expect(res2.status).toBe(200);
  });

  it("empty — 핀이 하나도 없다", async () => {
    resetScenario("empty");
    const pins = await fetch(`${BASE}/maps/map_1/pins`).then((r) => r.json());
    expect(pins.length).toBe(0);
  });

  it("중복 핀은 409 PIN_DUPLICATE", async () => {
    const res = await fetch(`${BASE}/maps/map_1/pins`, {
      method: "POST",
      body: JSON.stringify({ category: "음식점", source: "search", place_id: "kakao:mock-1", place_name: "해운대 밀면", lat: 35.1631, lng: 129.1639 }),
    });
    expect(res.status).toBe(201);
    const res2 = await fetch(`${BASE}/maps/map_1/pins`, {
      method: "POST",
      body: JSON.stringify({ category: "음식점", source: "search", place_id: "kakao:mock-1", place_name: "해운대 밀면", lat: 35.1631, lng: 129.1639 }),
    });
    expect(res2.status).toBe(409);
  });

  it("#382 실시간 핀: 카카오 장소 ID·검색어·메모만 받고 이름·좌표는 없다. 같은 장소는 409", async () => {
    const body = { source: "live", category: "음식점", kakao_place_id: "kakao:live-1", search_query: "성수 곱창", memo: "여기 곱창 맛있대" };
    const res = await fetch(`${BASE}/maps/map_1/pins`, { method: "POST", body: JSON.stringify(body) });
    expect(res.status).toBe(201);
    const pin = await res.json();
    expect(pin.source).toBe("live");
    expect(pin.kakao_place_id).toBe("kakao:live-1");
    expect(pin.search_query).toBe("성수 곱창");
    expect(pin.memo).toBe("여기 곱창 맛있대");
    expect(pin.lat).toBeUndefined();
    expect(pin.lng).toBeUndefined();
    expect(pin.place_name).toBeUndefined();
    const dup = await fetch(`${BASE}/maps/map_1/pins`, { method: "POST", body: JSON.stringify(body) });
    expect(dup.status).toBe(409);
    // 반응은 자체 DB 핀과 똑같이 된다
    const react = await fetch(`${BASE}/pins/${pin.id}/reaction`, { method: "PUT", body: JSON.stringify({ type: "like" }) });
    expect(react.status).toBe(200);
  });

  it("#382 자체 DB에 없는 장소는 검색에서 pinnable:false, search 로는 422, live 로는 핀이 된다", async () => {
    const items = await fetch(`${BASE}/places/search?q=${encodeURIComponent("곱창")}`).then((r) => r.json());
    expect(items[0]).toMatchObject({ place_id: "kakao:mock-6", pinnable: false });
    const asSearch = await fetch(`${BASE}/maps/map_1/pins`, {
      method: "POST",
      body: JSON.stringify({ category: "음식점", source: "search", place_id: "kakao:mock-6", place_name: "성수 노포 곱창", lat: 37.5445, lng: 127.0557 }),
    });
    expect(asSearch.status).toBe(422);
    expect((await asSearch.json()).code).toBe("PLACE_NOT_SUPPORTED");
    const asLive = await fetch(`${BASE}/maps/map_1/pins`, {
      method: "POST",
      body: JSON.stringify({ source: "live", category: "음식점", kakao_place_id: "kakao:mock-6", search_query: "곱창" }),
    });
    expect(asLive.status).toBe(201);
  });

  it("#382 실시간 핀은 필수 값이 빠지거나 숙소·기타면 422", async () => {
    const noQuery = await fetch(`${BASE}/maps/map_1/pins`, { method: "POST", body: JSON.stringify({ source: "live", category: "음식점", kakao_place_id: "kakao:live-2" }) });
    expect(noQuery.status).toBe(422);
    const lodging = await fetch(`${BASE}/maps/map_1/pins`, { method: "POST", body: JSON.stringify({ source: "live", category: "숙소", kakao_place_id: "kakao:live-3", search_query: "호텔" }) });
    expect(lodging.status).toBe(422);
  });

  it("#382 좌표가 없는 실시간 핀은 동선에서 빠진다", async () => {
    const make = async (id: string) =>
      (await fetch(`${BASE}/maps/map_1/pins`, { method: "POST", body: JSON.stringify({ source: "live", category: "음식점", kakao_place_id: id, search_query: "곱창" }) })).json();
    const live = await make("kakao:live-4");
    await fetch(`${BASE}/maps/map_1/shortlist`, { method: "POST", body: JSON.stringify({ pin_id: live.id }) });
    const routes = await fetch(`${BASE}/maps/map_1/route`, { method: "POST" }).then((r) => r.json());
    expect(routes.flatMap((r: { ordered_pin_ids: string[] }) => r.ordered_pin_ids)).not.toContain(live.id);
  });
});

describe("#139 — 외부 지도 SDK 요청은 목 서버가 가로채지 않는다", () => {
  it("카카오맵 SDK 주소가 `*/maps/:mapId` 핸들러에 잡혀 404가 되지 않는다", async () => {
    let body = "";
    try {
      body = await fetch("https://dapi.kakao.com/v2/maps/sdk.js").then((r) => r.text());
    } catch {
      // 네트워크가 없으면 요청이 실제로 밖으로 나가려다 실패한 것 — 목 서버가 가로채지 않았다는 뜻이다.
    }
    expect(body).not.toContain('"code":"NOT_FOUND"');
  }, 15000);
});

describe("#369 — 지도 삭제, 나가기, 방장 위임", () => {
  const me = () => store.members["map_1"]?.find((m) => m.user_id === "u_me");

  it("지도 응답에 요청자 기준 permissions가 붙고, 상세에서만 next_owner가 온다", async () => {
    const detail = await (await fetch(`${BASE}/maps/map_1`)).json();
    expect(detail.permissions).toEqual({ can_delete: true, can_leave: true });
    expect(detail.next_owner.user_id).toBe("u_2");
    const list = await (await fetch(`${BASE}/maps`)).json();
    expect(list[0].permissions.can_delete).toBe(true);
    expect(list[0].next_owner).toBeUndefined();
  });

  it("방장이 나가면 다음 사람이 방장이 되고 member.left에 실린다", async () => {
    const before = store.eventLog.length;
    expect((await fetch(`${BASE}/maps/map_1/members/me`, { method: "DELETE" })).status).toBe(204);
    expect(me()).toBeUndefined();
    expect(store.members["map_1"].find((m) => m.user_id === "u_2")?.role).toBe("owner");
    const ev = store.eventLog.slice(before).find((e) => e.type === "member.left");
    expect(ev?.data).toMatchObject({ user_id: "u_me", new_owner_user_id: "u_2" });
  });

  it("넘길 사람이 없는 방장은 409 OWNER_CANNOT_LEAVE, can_leave=false", async () => {
    store.members["map_1"] = store.members["map_1"].filter((m) => m.user_id === "u_me");
    const detail = await (await fetch(`${BASE}/maps/map_1`)).json();
    expect(detail.permissions).toEqual({ can_delete: true, can_leave: false });
    const r = await fetch(`${BASE}/maps/map_1/members/me`, { method: "DELETE" });
    expect(r.status).toBe(409);
    expect((await r.json()).code).toBe("OWNER_CANNOT_LEAVE");
  });

  it("방장이 아니면 삭제 403, 방장이 삭제하면 지도와 초대 토큰이 404", async () => {
    me()!.role = "member";
    expect((await fetch(`${BASE}/maps/map_1`, { method: "DELETE" })).status).toBe(403);
    me()!.role = "owner";
    const invite = await (await fetch(`${BASE}/maps/map_1/invite`, { method: "POST" })).json();
    expect((await fetch(`${BASE}/maps/map_1`, { method: "DELETE" })).status).toBe(204);
    expect((await fetch(`${BASE}/maps/map_1`)).status).toBe(404);
    expect((await (await fetch(`${BASE}/invites/${invite.token}/accept`, { method: "POST" })).json()).code).toBe("INVITE_NOT_FOUND");
    expect(await (await fetch(`${BASE}/maps`)).json()).toEqual([]);
  });
});

describe("#369 — 내 지도 10개 상한", () => {
  const create = () =>
    fetch(`${BASE}/maps`, { method: "POST", body: JSON.stringify({ title: "상한 시험", start_date: "2026-11-01", end_date: "2026-11-02" }) });

  it("내 지도가 10개면 만들기가 409 MAP_LIMIT, 하나 지우면 다시 된다", async () => {
    while ((await (await fetch(`${BASE}/maps`)).json()).length < 10) expect((await create()).status).toBe(201);
    const r = await create();
    expect(r.status).toBe(409);
    expect(await r.json()).toMatchObject({ code: "MAP_LIMIT", detail: { limit: 10, count: 10 } });
    const [last] = await (await fetch(`${BASE}/maps`)).json();
    expect((await fetch(`${BASE}/maps/${last.id}`, { method: "DELETE" })).status).toBe(204);
    expect((await create()).status).toBe(201);
  });
});

describe("#22·#24 — 내 지도 목록 + 지도 생성 지역(선택)", () => {
  it("GET /maps는 내가 구성원인 지도만 최근 생성순으로 준다", async () => {
    const created = await fetch(`${BASE}/maps`, {
      method: "POST",
      body: JSON.stringify({ title: "제주 여행", start_date: "2026-11-01", end_date: "2026-11-03" }),
    }).then((r) => r.json());

    const list = await fetch(`${BASE}/maps`).then((r) => r.json());
    expect(list[0].id).toBe(created.id); // 방금 만든 게 가장 최근이라 맨 앞
    expect(list.some((m: { id: string }) => m.id === "map_1")).toBe(true); // 시드 지도도 이미 구성원
  });

  it("POST /maps에 region을 실으면 그대로 저장·응답된다", async () => {
    const res = await fetch(`${BASE}/maps`, {
      method: "POST",
      body: JSON.stringify({
        title: "부산 여행", start_date: "2026-12-01", end_date: "2026-12-03",
        region: { label: "부산", lat: 35.1796, lng: 129.0756 },
      }),
    });
    expect(res.status).toBe(201);
    const body = await res.json();
    expect(body.region).toEqual({ label: "부산", lat: 35.1796, lng: 129.0756 });
  });

  it("region 없이 POST /maps — 기존 동작 그대로(회귀 없음)", async () => {
    const res = await fetch(`${BASE}/maps`, {
      method: "POST",
      body: JSON.stringify({ title: "당일치기", start_date: "2026-12-10", end_date: "2026-12-10" }),
    });
    expect(res.status).toBe(201);
    const body = await res.json();
    expect(body.region).toBeUndefined();
  });
});

describe("FE 스펙 갭 (2026-09-30, #154·#155)", () => {
  const post = (path: string, body?: unknown) =>
    fetch(`${BASE}${path}`, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

  it("숙소 핀에는 반응을 남길 수 없다 — can_react=false, PUT은 422 REACTION_NOT_ALLOWED", async () => {
    // v1에서는 숙소 핀을 만들 수 없지만(아래 #191 테스트), 반응 불가 규칙은 숙소 핀이 있을 때 그대로 적용된다 — 시드로 직접 넣는다
    const base = Object.values(store.pins)[0];
    const pin = { ...base, id: "stay_seed", category: "숙소" as const, place_name: "시드 숙소" };
    store.pins[pin.id] = pin;
    store.reactions[pin.id] = [];
    const list = await fetch(`${BASE}/maps/map_1/pins`).then((r) => r.json());
    expect(list.find((p: { id: string }) => p.id === pin.id).permissions.can_react).toBe(false);
    const res = await fetch(`${BASE}/pins/${pin.id}/reaction`, { method: "PUT", body: JSON.stringify({ type: "like" }) });
    expect(res.status).toBe(422);
    expect((await res.json()).code).toBe("REACTION_NOT_ALLOWED");
  });

  it("내 반응(my_reaction)과 구성원 의견 목록(reason_chip_ids 포함)", async () => {
    await fetch(`${BASE}/pins/pin_1/reaction`, {
      method: "PUT",
      body: JSON.stringify({ type: "against", reason_text: "매워요", reason_chip_ids: ["food_spicy"] }),
    });
    const list = await fetch(`${BASE}/maps/map_1/pins`).then((r) => r.json());
    expect(list.find((p: { id: string }) => p.id === "pin_1").my_reaction.type).toBe("against");
    const opinions = await fetch(`${BASE}/pins/pin_1/reactions`).then((r) => r.json());
    const mine = opinions.find((o: { user_id: string }) => o.user_id === "u_me");
    expect(mine.reason_chip_ids).toEqual(["food_spicy"]);
    expect(typeof mine.display_name).toBe("string");
    await fetch(`${BASE}/pins/pin_1/reaction`, { method: "DELETE" });
    const after = await fetch(`${BASE}/maps/map_1/pins`).then((r) => r.json());
    expect(after.find((p: { id: string }) => p.id === "pin_1").my_reaction).toBeNull();
  });

  it("초대 요약 GET /invites/{token} — 요약·없는 토큰 404", async () => {
    const inv = await post("/maps/map_1/invite").then((r) => r.json());
    const res = await fetch(`${BASE}/invites/${inv.token}`);
    expect(res.status).toBe(200);
    const summary = await res.json();
    expect(summary.title).toBeTruthy();
    expect(summary).not.toHaveProperty("map_id");
    expect(summary).toHaveProperty("member_count");
    expect(summary).not.toHaveProperty("pins");
    const missing = await fetch(`${BASE}/invites/nope`);
    expect(missing.status).toBe(404);
    expect((await missing.json()).code).toBe("INVITE_NOT_FOUND");
  });

  it("이름 수정 PATCH /auth/me — 계정 단위, 빈 이름은 422", async () => {
    const ok = await fetch(`${BASE}/auth/me`, { method: "PATCH", body: JSON.stringify({ display_name: "새이름" }) });
    expect(ok.status).toBe(200);
    expect((await fetch(`${BASE}/auth/me`).then((r) => r.json())).display_name).toBe("새이름");
    const bad = await fetch(`${BASE}/auth/me`, { method: "PATCH", body: JSON.stringify({ display_name: "" }) });
    expect(bad.status).toBe(422);
  });

  it("반경 넓히기는 +5분씩, 도보 30분 상한에서 409 WIDEN_LIMIT", async () => {
    resetScenario("region-conflict");
    const runId = "run_region_conflict";
    const radii: number[] = [];
    for (let i = 0; i < 3; i++) {
      const res = await post(`/runs/${runId}/widen`);
      expect(res.status).toBe(202);
      radii.push((await res.json()).default_radius_walk_min);
    }
    expect(radii).toEqual([20, 25, 30]);
    const over = await post(`/runs/${runId}/widen`);
    expect(over.status).toBe(409);
    expect((await over.json()).code).toBe("WIDEN_LIMIT");
  });
});

describe("#180 — GET /places/search (이름 검색)", () => {
  const search = (qs: string) => fetch(`${BASE}/places/search?${qs}`);

  it("이름이 맞는 장소를 돌려주고, 핀 생성에 필요한 필드가 전부 있다", async () => {
    const res = await search("q=" + encodeURIComponent("해운대"));
    expect(res.status).toBe(200);
    const items = await res.json();
    expect(items.length).toBeGreaterThan(0);
    for (const item of items) {
      expect(item).toMatchObject({ place_id: expect.any(String), place_name: expect.any(String), lat: expect.any(Number), lng: expect.any(Number) });
    }
  });

  it("결과가 없으면 빈 배열이다(가드레일 2 — 지어내지 않는다)", async () => {
    const res = await search("q=" + encodeURIComponent("없는가게없는가게"));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual([]);
  });

  it("lat·lng를 주면 가까운 곳이 먼저 온다", async () => {
    const res = await search("q=" + encodeURIComponent("해운대") + "&lat=35.1587&lng=129.1604");
    const items = await res.json();
    expect(items[0].place_id).toBe("kakao:mock-2");
  });

  it("검증 실패는 422 — 빈 검색어, 51자, lat만 보냄, limit 범위 밖", async () => {
    for (const qs of ["q=", "q=" + "가".repeat(51), "q=a&lat=35", "q=a&limit=16"]) {
      const res = await search(qs);
      expect(res.status, qs).toBe(422);
      expect((await res.json()).code).toBe("VALIDATION_ERROR");
    }
  });

  it("지도 API 장애는 503 PLACES_UNAVAILABLE", async () => {
    const res = await search("q=__unavailable__");
    expect(res.status).toBe(503);
    expect((await res.json()).code).toBe("PLACES_UNAVAILABLE");
  });
});

describe("#191 — 핀은 자체 DB 장소를 가리킨다 (핀 생성 규칙)", () => {
  const create = (body: unknown) => fetch(`${BASE}/maps/map_1/pins`, { method: "POST", body: JSON.stringify(body) });

  it("검색 결과를 골라 만든 핀은 장소의 이름·좌표·place_url을 쓴다(요청의 이름·좌표는 힌트일 뿐)", async () => {
    const res = await create({ category: "관광지", source: "search", place_id: "kakao:mock-3", place_name: "내가 바꾼 이름", lat: 1, lng: 2 });
    expect(res.status).toBe(201);
    const pin = await res.json();
    expect(pin.place_name).toBe("광안리 해변");
    expect(pin.lat).toBeCloseTo(35.1532, 3);
    expect(pin.lng).toBeCloseTo(129.1186, 3);
  });

  it("place_url이 있는 장소는 핀에 place_url이 실린다", async () => {
    const pin = await (await create({ category: "음식점", source: "search", place_id: "kakao:mock-1", place_name: "해운대 밀면", lat: 35.1631, lng: 129.1639 })).json();
    expect(pin.place_url).toContain("place.map.kakao.com");
  });

  it("자체 DB에 짝이 없는 장소는 422 PLACE_NOT_SUPPORTED", async () => {
    const res = await create({ category: "음식점", source: "search", place_id: "kakao:no-such-place", place_name: "없는 곳", lat: 35.1, lng: 129.0 });
    expect(res.status).toBe(422);
    expect((await res.json()).code).toBe("PLACE_NOT_SUPPORTED");
  });

  it("지도 길게 누르기(coordinate)와 링크는 v1에서 422 VALIDATION_ERROR", async () => {
    for (const body of [
      { category: "음식점", source: "coordinate", lat: 35.1, lng: 129.0 },
      { category: "음식점", source: "link", link_url: "https://maps.app.goo.gl/x" },
      { category: "음식점", lat: 35.1, lng: 129.0 },
    ]) {
      const res = await create(body);
      expect(res.status, JSON.stringify(body)).toBe(422);
      expect((await res.json()).code).toBe("VALIDATION_ERROR");
    }
  });

  it("숙소·기타 장소는 자체 DB에 없어 핀을 만들 수 없다 — 422 PLACE_NOT_SUPPORTED", async () => {
    const res = await create({ category: "숙소", source: "search", place_id: "kakao:mock-4", place_name: "광안리 게스트하우스", lat: 35.1547, lng: 129.1191 });
    expect(res.status).toBe(422);
    expect((await res.json()).code).toBe("PLACE_NOT_SUPPORTED");
  });

  it("매칭 힌트(place_name·lat·lng)가 빠지면 422", async () => {
    const res = await create({ category: "음식점", source: "search", place_id: "kakao:mock-1" });
    expect(res.status).toBe(422);
    expect((await res.json()).code).toBe("VALIDATION_ERROR");
  });

  it("검색 결과의 pinnable로 핀이 될 수 있는 장소를 미리 안다(숙소·기타는 false)", async () => {
    const items = await fetch(`${BASE}/places/search?q=` + encodeURIComponent("광안리")).then((r) => r.json());
    const byId = Object.fromEntries(items.map((i: { place_id: string; pinnable: boolean }) => [i.place_id, i.pinnable]));
    expect(byId["kakao:mock-3"]).toBe(true);
    expect(byId["kakao:mock-4"]).toBe(false);
  });

  it("요청 category가 장소의 분류와 다르면 422", async () => {
    const res = await create({ category: "카페", source: "search", place_id: "kakao:mock-1" });
    expect(res.status).toBe(422);
    expect((await res.json()).code).toBe("VALIDATION_ERROR");
  });
});

describe("realtime SSE (docs/events.md)", () => {
  const createCafePin = () =>
    fetch(`${BASE}/maps/map_1/pins`, {
      method: "POST",
      body: JSON.stringify({ category: "카페", source: "search", place_id: "kakao:mock-2", place_name: "해운대 바다 카페", lat: 35.1587, lng: 129.1604 }),
    });

  // "핀을 만들면 이벤트가 쌓인다"는 시간과 무관하다 — 스트림·타이머를 거치지 않고 로그를 직접 본다.
  it("핀을 만들면 event_log에 public pin.created가 seq와 함께 쌓인다", async () => {
    const before = store.eventLog.length;
    expect((await createCafePin()).status).toBe(201);
    const added = store.eventLog.slice(before);
    expect(added.map((e) => e.type)).toEqual(["pin.created"]);
    expect(added[0].channel).toBe("public");
    expect(added[0].map_id).toBe("map_1");
    expect(added[0].seq).toBeGreaterThan(0);
  });

  // 스트림은 형식(헤더·id/event/data 줄)만 본다. 이벤트를 **연결 전에** 만들어 두면 Last-Event-ID 0부터 다시 보내므로
  // "연결과 생성 중 어느 쪽이 먼저냐"에 결과가 달라지지 않는다.
  it("스트림은 쌓여 있는 이벤트를 id/event/data 형식으로 보낸다", async () => {
    await createCafePin();
    const stream = await fetch(`${BASE}/maps/map_1/events`);
    expect(stream.status).toBe(200);
    expect(stream.headers.get("content-type")).toContain("text/event-stream");

    const reader = stream.body!.getReader();
    const decoder = new TextDecoder();
    let received = "";
    while (!received.includes("pin.created")) {
      const { value, done } = await reader.read();
      if (done) break;
      received += decoder.decode(value);
    }
    // reader.cancel()을 기다리면 msw/undici가 스트림을 닫는 데 4~8초가 걸릴 수 있어 기다리지 않는다.
    void reader.cancel().catch(() => undefined);

    expect(received).toContain("event: pin.created");
    expect(received).toMatch(/id: \d+/);
    expect(received).toMatch(/data: \{/);
  }, 10000);
});

describe("FE 요청 필드 6건과 반대 사유 칩 (2026-10-04, #60)", () => {
  it("Pin.created_at — 시드 핀마다 있고, 새로 찍은 핀이 가장 최근이다", async () => {
    const pins = await fetch(`${BASE}/maps/map_1/pins`).then((r) => r.json());
    for (const p of pins) expect(Number.isNaN(Date.parse(p.created_at))).toBe(false);
    const created = await fetch(`${BASE}/maps/map_1/pins`, {
      method: "POST",
      body: JSON.stringify({ category: "음식점", source: "search", place_id: "kakao:mock-1", place_name: "x", lat: 0, lng: 0 }),
    });
    if (created.status === 201) {
      const pin = await created.json();
      expect(Date.parse(pin.created_at)).toBeGreaterThanOrEqual(Math.max(...pins.map((p: { created_at: string }) => Date.parse(p.created_at))));
    }
  });

  it("counts — 의견을 남긴 구성원 수/전체 구성원 수", async () => {
    const counts = await fetch(`${BASE}/maps/map_1/counts`).then((r) => r.json());
    expect(counts.members_total).toBe(4);
    // 시드 반응 5개 = u_me·u_2·u_3·u_4 → 4명이 남겼다
    expect(counts.members_with_opinion).toBe(4);
  });

  it("Map.pin_count·InviteSummary.pin_count — 지금 있는 핀 수", async () => {
    const map = await fetch(`${BASE}/maps/map_1`).then((r) => r.json());
    expect(map.pin_count).toBe(3);
    await fetch(`${BASE}/pins/pin_3`, { method: "DELETE" });
    const after = await fetch(`${BASE}/maps/map_1`).then((r) => r.json());
    expect(after.pin_count).toBe(2);
    const inv = await fetch(`${BASE}/maps/map_1/invite`, { method: "POST" }).then((r) => r.json());
    const summary = await fetch(`${BASE}/invites/${inv.token}`).then((r) => r.json());
    expect(summary.pin_count).toBe(2);
    expect(summary.pins).toBeUndefined(); // 개수만, 핀 내용은 주지 않는다
  });

  it("Member.role — 방장은 owner 한 명, 나머지는 member", async () => {
    const members = await fetch(`${BASE}/maps/map_1/members`).then((r) => r.json());
    expect(members.filter((m: { role: string }) => m.role === "owner")).toHaveLength(1);
    expect(members.every((m: { role: string }) => ["owner", "member"].includes(m.role))).toBe(true);
  });

  it("칩 목록 — 카테고리 칩 다음에 공통 칩, 숙소·기타는 빈 배열", async () => {
    const food = await fetch(`${BASE}/categories/${encodeURIComponent("음식점")}/reason-chips`).then((r) => r.json());
    expect(food.map((c: { id: string }) => c.id)).toContain("food_spicy");
    expect(food.slice(-2).map((c: { id: string }) => c.id)).toEqual(["common_not_my_taste", "common_far"]);
    const lodging = await fetch(`${BASE}/categories/${encodeURIComponent("숙소")}/reason-chips`).then((r) => r.json());
    expect(lodging).toEqual([]);
  });

  it("칩 id 검증 — 이름을 그대로 보내거나 다른 카테고리 칩은 422 VALIDATION_ERROR", async () => {
    const byName = await fetch(`${BASE}/pins/pin_1/reaction`, { method: "PUT", body: JSON.stringify({ type: "against", reason_chip_ids: ["매워요"] }) });
    expect(byName.status).toBe(422);
    expect((await byName.json()).code).toBe("VALIDATION_ERROR");
    const otherCategory = await fetch(`${BASE}/pins/pin_1/reaction`, { method: "PUT", body: JSON.stringify({ type: "against", reason_chip_ids: ["cafe_noisy"] }) });
    expect(otherCategory.status).toBe(422);
    const common = await fetch(`${BASE}/pins/pin_1/reaction`, { method: "PUT", body: JSON.stringify({ type: "against", reason_chip_ids: ["common_far"] }) });
    expect(common.status).toBe(200);
  });

  it("reaction.changed — 남긴 사람과 종류가 실린다(삭제면 type null)", async () => {
    const before = store.eventLog.length;
    await fetch(`${BASE}/pins/pin_1/reaction`, { method: "PUT", body: JSON.stringify({ type: "like" }) });
    await fetch(`${BASE}/pins/pin_1/reaction`, { method: "DELETE" });
    const events = store.eventLog.slice(before).filter((e) => e.type === "reaction.changed");
    expect(events).toHaveLength(2);
    const [put, del] = events.map((e) => e.data as { user_id: string; display_name: string; type: string | null });
    expect(put).toMatchObject({ user_id: "u_me", type: "like" });
    expect(typeof put.display_name).toBe("string");
    expect(del.type).toBeNull();
  });
});

describe("#340·회의 14번 — 지도 목록 구분과 후보 좌표", () => {
  it("내가 만든 지도는 my_role=owner, created_by_me=true", async () => {
    const maps = await fetch(`${BASE}/maps`).then((r) => r.json());
    expect(maps[0]).toMatchObject({ my_role: "owner", created_by_me: true });
    expect(maps[0].created_by).toBeUndefined(); // 목 서버 내부 값은 응답에 새지 않는다
  });

  it("방장을 넘기고 나면 my_role과 created_by_me가 달라질 수 있다(내가 만들었지만 이제 방장이 아님)", async () => {
    const m = store.members["map_1"];
    m.find((x) => x.user_id === "u_me")!.role = "member";
    m.find((x) => x.user_id === "u_2")!.role = "owner";
    const one = await fetch(`${BASE}/maps/map_1`).then((r) => r.json());
    expect(one).toMatchObject({ my_role: "member", created_by_me: true });
  });

  it("추천 후보에는 자체 DB 장소의 좌표가 있다", async () => {
    const run = await fetch(`${BASE}/maps/map_1/runs`, { method: "POST", body: JSON.stringify({ category: "음식점" }) }).then((r) => r.json());
    await fetch(`${BASE}/runs/${run.id}/regions/confirm`, { method: "POST", body: JSON.stringify({ region_labels: ["제주시 권역"] }) }).catch(() => undefined);
    const exec = await fetch(`${BASE}/runs/${run.id}/execute`, { method: "POST" });
    expect(exec.ok).toBe(true);
    const result = await fetch(`${BASE}/runs/${run.id}/result`).then((r) => r.json());
    for (const c of result.candidates) {
      expect(typeof c.lat).toBe("number");
      expect(typeof c.lng).toBe("number");
    }
  });
});
