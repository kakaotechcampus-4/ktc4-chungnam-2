import { afterAll, beforeAll, afterEach, describe, expect, it } from "vitest";
import { server } from "./node";
import { resetScenario } from "./scenarios";
import { store } from "./store";
import { MAP_LIMIT } from "./handlers/maps";

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

    // 아직 게시 전이므로 후보는 핀 목록에 없다(후보는 candidates, 핀이 아니다)
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
  it("evidence-limit — 「+」는 선호로 붙고, 한 번에 글 5개, run 하나에 글 10개까지(#707)", async () => {
    const run = await fetch(`${BASE}/maps/map_1/runs`, { method: "POST", body: JSON.stringify({ category: "음식점" }) }).then((r) => r.json());
    const patch = (texts: string[]) =>
      fetch(`${BASE}/runs/${run.id}/evidence`, { method: "PATCH", body: JSON.stringify({ add: texts.map((text) => ({ text })) }) });
    expect((await patch(["1", "2", "3", "4", "5", "6"])).status).toBe(422);
    // 한 요청 안의 같은 글은 하나로 친다(글 수로 센다)
    expect((await patch(["같은 글", "같은 글"])).status).toBe(200);
    const first = await patch(["회 좋아해", "2", "3", "4"]);
    expect(first.status).toBe(200);
    const lines = await first.json();
    expect(lines.find((l: { text: string }) => l.text === "회 좋아해").badge).toBe("preferred");
    expect((await patch(["6", "7", "8", "9", "10"])).status).toBe(200);
    const over = await patch(["11"]);
    expect(over.status).toBe(409);
    const body = await over.json();
    expect(body.code).toBe("EVIDENCE_LIMIT");
    expect(body.detail).toEqual({ limit: 10, used: 10 }); // 같은 글 1 + 4 + 5
  });

  it("no-results — 결과 0개는 404 NO_RESULTS", async () => {
    resetScenario("no-results");
    const res = await fetch(`${BASE}/runs/run_no_results/result`);
    expect(res.status).toBe(404);
    const body = await res.json();
    expect(body.code).toBe("NO_RESULTS");
    expect(body.detail.funnel.length).toBeGreaterThan(0);
    expect(body.detail.funnel.map((f: { label: string }) => f.label)).toContain("추천 가능 아님 제거");
  });

  it("retry-limit — 10회 초과 시 429 RETRY_LIMIT(detail에 attempt_limit)", async () => {
    resetScenario("retry-limit");
    const res = await fetch(`${BASE}/runs/run_retry_limit/retry`, { method: "POST" });
    expect(res.status).toBe(429);
    const body = await res.json();
    expect(body.code).toBe("RETRY_LIMIT");
    expect(body.detail).toMatchObject({ attempt_no: 10, attempt_limit: 10 });
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
    expect(pin.place_url).toBe("https://place.map.kakao.com/live-1");   // #445 — 실시간 핀도 카카오 장소 페이지 링크
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
    expect(detail.permissions).toEqual({ can_delete: true, can_leave: true, can_edit: true });
    expect(detail.next_owner.user_id).toBe("u_2");
    const list = (await (await fetch(`${BASE}/maps`)).json()).items;
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
    expect(detail.permissions).toEqual({ can_delete: true, can_leave: false, can_edit: true });
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
    expect(await (await fetch(`${BASE}/maps`)).json()).toEqual({ items: [], limit: MAP_LIMIT });
  });
});

describe("#465·#467·#468 — 지도 수정, 초대 링크 관리, 방장 넘기기", () => {
  const me = () => store.members["map_1"]?.find((m) => m.user_id === "u_me");
  const send = (path: string, method: string, body?: unknown) =>
    fetch(`${BASE}${path}`, { method, ...(body ? { body: JSON.stringify(body) } : {}) });

  it("PATCH /maps/{id}: 보낸 필드만 바꾸고 map.updated를 보낸다. 방장이 아니면 403, 날짜 역전·빈 객체는 422", async () => {
    const before = store.eventLog.length;
    const r = await send("/maps/map_1", "PATCH", { title: "새 제목" });
    expect(r.status).toBe(200);
    const body = await r.json();
    expect(body.title).toBe("새 제목");
    expect(body.permissions.can_edit).toBe(true);
    const ev = store.eventLog.slice(before).find((e) => e.type === "map.updated");
    expect(ev?.data).toMatchObject({ map_id: "map_1", title: "새 제목" });

    expect((await send("/maps/map_1", "PATCH", { end_date: "2000-01-01" })).status).toBe(422);
    expect((await send("/maps/map_1", "PATCH", {})).status).toBe(422);
    me()!.role = "member";
    expect((await send("/maps/map_1", "PATCH", { title: "x" })).status).toBe(403);
  });

  it("방장 넘기기: 나는 구성원으로 남고 owner.changed가 간다. 나 자신·비구성원은 422 OWNER_TARGET_INVALID, 구성원은 403", async () => {
    const before = store.eventLog.length;
    expect((await send("/maps/map_1/owner", "POST", { user_id: "u_me" })).status).toBe(422);
    const bad = await send("/maps/map_1/owner", "POST", { user_id: "nobody" });
    expect(bad.status).toBe(422);
    expect((await bad.json()).code).toBe("OWNER_TARGET_INVALID");

    const ok = await send("/maps/map_1/owner", "POST", { user_id: "u_2" });
    expect(ok.status).toBe(200);
    const map = await ok.json();
    expect(map.my_role).toBe("member");
    expect(map.permissions.can_edit).toBe(false);
    expect(me()?.role).toBe("member");
    expect(store.members["map_1"].find((m) => m.user_id === "u_2")?.role).toBe("owner");
    const ev = store.eventLog.slice(before).find((e) => e.type === "owner.changed");
    expect(ev?.data).toEqual({ map_id: "map_1", from_user_id: "u_me", to_user_id: "u_2" });
    expect((await send("/maps/map_1/owner", "POST", { user_id: "u_me" })).status).toBe(403);
  });

  it("초대 링크: 내 유효한 링크는 재사용(200), 목록에 보이고, 끄면 목록에서 빠지며 요약·수락이 410 INVITE_REVOKED", async () => {
    const first = await send("/maps/map_1/invite", "POST");
    expect(first.status).toBe(201);
    const { token } = await first.json();
    const again = await send("/maps/map_1/invite", "POST");
    expect(again.status).toBe(200);
    expect((await again.json()).token).toBe(token);

    const list = await (await fetch(`${BASE}/maps/map_1/invites`)).json();
    expect(list.map((i: { token: string }) => i.token)).toEqual([token]);
    expect(list[0]).toMatchObject({ used_count: 0 });

    expect((await send(`/invites/${token}`, "DELETE")).status).toBe(204);
    expect((await send(`/invites/${token}`, "DELETE")).status).toBe(204); // 멱등
    expect(await (await fetch(`${BASE}/maps/map_1/invites`)).json()).toEqual([]);
    for (const r of [await fetch(`${BASE}/invites/${token}`), await send(`/invites/${token}/accept`, "POST")]) {
      expect(r.status).toBe(410);
      expect((await r.json()).code).toBe("INVITE_REVOKED");
    }
    expect((await send("/invites/nope", "DELETE")).status).toBe(404);

    const fresh = await (await send("/maps/map_1/invite", "POST")).json();
    expect(fresh.token).not.toBe(token); // 끈 링크는 재사용하지 않는다
  });

  it("방장이 아니면 초대 링크 목록·끄기가 403", async () => {
    const { token } = await (await send("/maps/map_1/invite", "POST")).json();
    me()!.role = "member";
    expect((await fetch(`${BASE}/maps/map_1/invites`)).status).toBe(403);
    expect((await send(`/invites/${token}`, "DELETE")).status).toBe(403);
  });
});

describe("#466·#473·#474 — 핀 수정, 지도를 눌러 핀, 링크 해석", () => {
  const send = (path: string, method: string, body?: unknown) =>
    fetch(`${BASE}${path}`, { method, ...(body ? { body: JSON.stringify(body) } : {}) });
  const liveBody = { source: "live", category: "음식점", kakao_place_id: "kakao:live-9", search_query: "삼겹살" };

  it("PATCH /pins: 메모를 바꾸고 지우며 pin.updated를 보낸다. 빈 객체·200자 초과는 422", async () => {
    const pin = await (await send("/maps/map_1/pins", "POST", liveBody)).json();
    expect(pin.permissions.can_edit).toBe(true);
    const before = store.eventLog.length;
    const r = await send(`/pins/${pin.id}`, "PATCH", { memo: "곱창 맛있대" });
    expect(r.status).toBe(200);
    expect((await r.json()).memo).toBe("곱창 맛있대");
    expect(store.eventLog.slice(before).find((e) => e.type === "pin.updated")?.data).toMatchObject({ id: pin.id, memo: "곱창 맛있대" });

    expect((await (await send(`/pins/${pin.id}`, "PATCH", { memo: "" })).json()).memo).toBeUndefined();
    expect((await send(`/pins/${pin.id}`, "PATCH", {})).status).toBe(422);
    expect((await send(`/pins/${pin.id}`, "PATCH", { memo: "가".repeat(201) })).status).toBe(422);
  });

  it("PATCH /pins: 분류는 live 핀이고 반응이 없을 때만, 숙소는 422", async () => {
    const pin = await (await send("/maps/map_1/pins", "POST", liveBody)).json();
    expect((await send(`/pins/${pin.id}`, "PATCH", { category: "숙소" })).status).toBe(422);
    const ok = await send(`/pins/${pin.id}`, "PATCH", { category: "카페" });
    expect(ok.status).toBe(200);
    expect((await ok.json()).category).toBe("카페");
    expect((await send(`/pins/${pin.id}/reaction`, "PUT", { type: "like" })).status).toBe(200);
    expect((await send(`/pins/${pin.id}`, "PATCH", { category: "음식점" })).status).toBe(422);
    const dbPin = (await (await fetch(`${BASE}/maps/map_1/pins`)).json()).find((p: { source?: string; created_by: string }) => p.source !== "live" && p.created_by === "u_me");
    expect((await send(`/pins/${dbPin.id}`, "PATCH", { category: "카페" })).status).toBe(422); // 자체 DB 핀의 분류는 장소가 정한다
  });

  it("PATCH /pins: 남이 찍은 핀은 403, 없는 핀은 404", async () => {
    const others = (await (await fetch(`${BASE}/maps/map_1/pins`)).json()).find((p: { created_by: string }) => p.created_by !== "u_me");
    expect(others.permissions.can_edit).toBe(false);
    expect((await send(`/pins/${others.id}`, "PATCH", { memo: "x" })).status).toBe(403);
    expect((await send("/pins/nope", "PATCH", { memo: "x" })).status).toBe(404);
  });

  it("POST /pins/{id}/resolve: 짝이 있으면 live 핀이 db 핀이 되고 반응·id는 유지, pin.updated, 힌트는 저장 안 함", async () => {
    const live = await (await send("/maps/map_1/pins", "POST", { source: "live", category: "카페", kakao_place_id: "kakao:live-2", search_query: "바다 카페" })).json();
    expect((await send(`/pins/${live.id}/reaction`, "PUT", { type: "like" })).status).toBe(200);
    const before = store.eventLog.length;
    const r = await send(`/pins/${live.id}/resolve`, "POST", { place_name: "해운대 바다 카페", lat: 35.1587, lng: 129.1604, address: "부산 해운대구 중동" });
    expect(r.status).toBe(200);
    const pin = await r.json();
    expect(pin).toMatchObject({ id: live.id, source: "db", place_name: "해운대 바다 카페", category: "카페" });
    expect(pin.kakao_place_id).toBeUndefined();
    expect(pin.search_query).toBeUndefined();
    expect(pin.reaction_summary.like).toBe(1); // 반응 유지
    expect(store.eventLog.slice(before).find((e) => e.type === "pin.updated")?.data).toMatchObject({ id: live.id, source: "db" });
    expect(JSON.stringify(pin)).not.toContain("부산 해운대구 중동"); // 힌트(주소)는 응답·저장에 없다
    // 이미 db 핀이면 변화 없음 200
    expect((await (await send(`/pins/${live.id}/resolve`, "POST", { place_name: "아무거나", lat: 1, lng: 1 })).json()).source).toBe("db");
  });

  it("POST /pins/{id}/resolve: 짝이 없으면 200 + live 그대로(이벤트 없음), 같은 장소 핀이 이미 있으면 409, 힌트 누락은 422", async () => {
    const live = await (await send("/maps/map_1/pins", "POST", { source: "live", category: "음식점", kakao_place_id: "kakao:mock-6", search_query: "곱창" })).json();
    const before = store.eventLog.length;
    const none = await send(`/pins/${live.id}/resolve`, "POST", { place_name: "성수 노포 곱창", lat: 37.5445, lng: 127.0557 });
    expect(none.status).toBe(200);
    expect((await none.json()).source).toBe("live");
    expect(store.eventLog.slice(before).some((e) => e.type === "pin.updated")).toBe(false);

    const dupLive = await (await send("/maps/map_1/pins", "POST", { source: "live", category: "음식점", kakao_place_id: "kakao:live-3", search_query: "밀면" })).json();
    const dbPin = await (await send("/maps/map_1/pins", "POST", { category: "음식점", place_id: "kakao:mock-1", place_name: "해운대 밀면", lat: 35.1631, lng: 129.1639 })).json();
    const dup = await send(`/pins/${dupLive.id}/resolve`, "POST", { place_name: "해운대 밀면", lat: 35.1631, lng: 129.1639 });
    expect(dup.status).toBe(409);
    expect((await dup.json()).detail.pin_id).toBe(dbPin.id);

    expect((await send(`/pins/${live.id}/resolve`, "POST", { lat: 1, lng: 1 })).status).toBe(422);
    expect((await send("/pins/nope/resolve", "POST", { place_name: "x", lat: 1, lng: 1 })).status).toBe(404);
  });

  it("GET /places/nearest: 100m 안 자체 DB 장소만 가까운 순, 없으면 빈 배열, lat·lng 없으면 422", async () => {
    const near = await (await fetch(`${BASE}/places/nearest?lat=35.1631&lng=129.1639`)).json();
    expect(near.map((p: { place_name: string }) => p.place_name)).toEqual(["해운대 밀면"]);
    expect(near.every((p: { pinnable: boolean }) => p.pinnable)).toBe(true);
    expect(await (await fetch(`${BASE}/places/nearest?lat=35.1631&lng=129.1639&category=카페`)).json()).toEqual([]);
    expect(await (await fetch(`${BASE}/places/nearest?lat=37.5&lng=127.0`)).json()).toEqual([]);
    expect((await fetch(`${BASE}/places/nearest?lat=35.1`)).status).toBe(422);
    // 자체 DB에 없는 곳(kakao:mock-6)은 가까워도 나오지 않는다
    expect(await (await fetch(`${BASE}/places/nearest?lat=37.5445&lng=127.0557`)).json()).toEqual([]);
  });

  it("POST /places/from-link: 구글은 이름·자체 DB 짝, 카카오는 장소 ID만(짝 없으면 검색어 필요), 그 밖은 422", async () => {
    const g = await (await send("/places/from-link", "POST", { url: "https://www.google.com/maps/place/해운대+밀면/@35.1631,129.1639,17z" })).json();
    expect(g).toMatchObject({ provider: "google", name_hint: "해운대 밀면", needs_search_query: false });
    expect(g.matches.map((p: { place_id: string }) => p.place_id)).toEqual(["kakao:mock-1"]);
    expect(g.lat).toBeUndefined(); // 링크 안의 좌표는 돌려주지 않는다

    const own = await (await send("/places/from-link", "POST", { url: "https://place.map.kakao.com/mock-1" })).json();
    expect(own).toMatchObject({ provider: "kakao", kakao_place_id: "kakao:mock-1", needs_search_query: false });
    const outside = await (await send("/places/from-link", "POST", { url: "https://place.map.kakao.com/mock-6" })).json();
    expect(outside).toMatchObject({ provider: "kakao", kakao_place_id: "kakao:mock-6", matches: [], needs_search_query: true });

    const naver = await send("/places/from-link", "POST", { url: "https://map.naver.com/p/entry/place/123" });
    expect(naver.status).toBe(422);
    expect((await naver.json()).code).toBe("LINK_NOT_SUPPORTED");
    expect((await (await send("/places/from-link", "POST", { url: "https://maps.app.goo.gl/fail" })).json()).code).toBe("LINK_UNRESOLVED");
    expect((await (await send("/places/from-link", "POST", { url: "not a url" })).json()).code).toBe("LINK_NOT_SUPPORTED");
  });
});

describe("#469·#471 — 지난 추천 기록, 확정 리스트 내보내기", () => {
  const send = (path: string, method: string, body?: unknown) =>
    fetch(`${BASE}${path}`, { method, ...(body ? { body: JSON.stringify(body) } : {}) });

  it("GET /maps/{id}/runs: 내가 만든 run만 최근순, 분류 필터·limit, 진행 중 run의 결과는 409 RUN_NOT_FINISHED", async () => {
    expect(await (await fetch(`${BASE}/maps/map_1/runs`)).json()).toEqual([]);
    const first = await (await send("/maps/map_1/runs", "POST", { category: "음식점" })).json();
    await new Promise((r) => setTimeout(r, 5));
    const second = await (await send("/maps/map_1/runs", "POST", { category: "음식점" })).json();
    store.runRequestedBy["run_other"] = "u_2"; // 남이 요청한 run — 목록에 없어야 한다(가드레일 1)
    store.runs["run_other"] = { id: "run_other", map_id: "map_1", category: "음식점", status: "done", attempt_no: 1 };

    const list = await (await fetch(`${BASE}/maps/map_1/runs`)).json();
    expect(list.map((r: { id: string }) => r.id)).toEqual([second.id, first.id]);
    expect(list[0]).toMatchObject({ map_id: "map_1", category: "음식점", status: "collecting_evidence", candidate_count: 0, published_count: 0 });
    expect(typeof list[0].created_at).toBe("string");
    expect(await (await fetch(`${BASE}/maps/map_1/runs?category=카페`)).json()).toEqual([]);
    expect((await fetch(`${BASE}/maps/map_1/runs?limit=1`).then((r) => r.json())).length).toBe(1);
    expect((await fetch(`${BASE}/maps/map_1/runs?limit=99`)).status).toBe(422);
    expect((await fetch(`${BASE}/maps/nope/runs`)).status).toBe(404);

    const notDone = await fetch(`${BASE}/runs/${first.id}/result`);
    expect(notDone.status).toBe(409);
    expect((await notDone.json()).code).toBe("RUN_NOT_FINISHED");
  });

  it("GET /maps/{id}/shortlist/export: txt는 확정 순서대로, csv는 BOM + 머리글, live 핀은 검색어 + 이름 확인 필요", async () => {
    const live = await (await send("/maps/map_1/pins", "POST", { source: "live", category: "음식점", kakao_place_id: "kakao:live-7", search_query: "삼겹살", memo: "여기, 맛있대" })).json();
    expect((await send("/maps/map_1/shortlist", "POST", { pin_id: live.id })).status).toBe(201);

    const txt = await fetch(`${BASE}/maps/map_1/shortlist/export`);
    expect(txt.status).toBe(200);
    expect(txt.headers.get("content-type")).toContain("text/plain");
    expect(txt.headers.get("content-disposition")).toContain("attachment");
    const lines = (await txt.text()).trim().split("\n");
    expect(lines.at(-1)).toContain("삼겹살 (이름 확인 필요)");
    expect(lines.at(-1)).toContain("https://place.map.kakao.com/live-7");

    const csv = await fetch(`${BASE}/maps/map_1/shortlist/export?format=csv`);
    expect(csv.headers.get("content-type")).toContain("text/csv");
    const bytes = new Uint8Array(await csv.clone().arrayBuffer());
    expect([...bytes.slice(0, 3)]).toEqual([0xef, 0xbb, 0xbf]); // 엑셀에서 한글이 깨지지 않게 UTF-8 BOM (fetch의 text()는 BOM을 벗기므로 바이트로 본다)
    const body = await csv.text();
    expect(body.split(/\r?\n/)[0]).toBe("순서,이름,분류,링크,메모");
    expect(body).toContain('"여기, 맛있대"'); // 쉼표가 든 칸은 따옴표로 감싼다

    expect((await fetch(`${BASE}/maps/map_1/shortlist/export?format=pdf`)).status).toBe(422);
    expect((await fetch(`${BASE}/maps/nope/shortlist/export`)).status).toBe(404);
  });

  it("확정 리스트가 비어 있으면 csv는 머리글만, txt는 안내 한 줄", async () => {
    store.shortlist["map_1"] = [];
    expect(await (await fetch(`${BASE}/maps/map_1/shortlist/export`)).text()).toBe("확정한 장소가 아직 없어요\n");
    expect((await (await fetch(`${BASE}/maps/map_1/shortlist/export?format=csv`)).text()).trim().split("\r\n").length).toBe(1);
  });
});

describe("#9 — 카톡 대화에서 뽑은 링크 미리보기·핀 일괄 생성", () => {
  const send = (path: string, method: string, body?: unknown) =>
    fetch(`${BASE}${path}`, { method, ...(body ? { body: JSON.stringify(body) } : {}) });
  const googleLink = (name: string) => `https://www.google.com/maps/place/${encodeURIComponent(name)}/@35.16,129.16,17z`;

  it("link-preview: 구글(이름)·카카오(ID)는 장소를 찾고, 네이버는 LINK_NOT_SUPPORTED, 항목마다 따로 결과", async () => {
    const r = await send("/maps/map_1/pins/link-preview", "POST", {
      urls: [googleLink("해운대 밀면"), "https://place.map.kakao.com/mock-2", "https://map.naver.com/p/entry/place/1", "https://place.map.kakao.com/mock-6", googleLink("없는 가게")],
    });
    expect(r.status).toBe(200);
    const { items } = await r.json();
    expect(items.map((i: { index: number }) => i.index)).toEqual([0, 1, 2, 3, 4]);
    expect(items[0]).toMatchObject({ status: "ok", result: { provider: "google", name_hint: "해운대 밀면" } });
    expect(items[0].result.matches[0].place_name).toBe("해운대 밀면");
    expect(items[1].result.matches[0].place_name).toBe("해운대 바다 카페");
    expect(items[2]).toMatchObject({ status: "error", error_code: "LINK_NOT_SUPPORTED" });
    expect(items[3].result).toMatchObject({ needs_search_query: true, kakao_place_id: "kakao:mock-6", matches: [] }); // 자체 DB에 없다
    expect(items[4].result.matches).toEqual([]); // 구글 링크인데 짝 없음 — 화면이 name_hint로 검색을 잇는다
    // 링크의 좌표·원문은 돌려주지 않는다(matches의 좌표는 자체 DB 장소의 값)
    for (const item of items) expect(item).not.toHaveProperty("url");
    for (const item of items.filter((i: { result?: object }) => i.result)) { expect(item.result).not.toHaveProperty("lat"); expect(item.result).not.toHaveProperty("lng"); }
  });

  it("link-preview: 이미 지도에 있는 장소는 already_pinned_pin_id, 빈 목록·10개 초과·없는 지도는 에러", async () => {
    const pin = await (await send("/maps/map_1/pins", "POST", { category: "음식점", place_id: "kakao:mock-1", place_name: "해운대 밀면", lat: 35.1631, lng: 129.1639 })).json();
    const { items } = await (await send("/maps/map_1/pins/link-preview", "POST", { urls: [googleLink("해운대 밀면")] })).json();
    expect(items[0].already_pinned_pin_id).toBe(pin.id);
    expect((await send("/maps/map_1/pins/link-preview", "POST", { urls: [] })).status).toBe(422);
    expect((await send("/maps/map_1/pins/link-preview", "POST", { urls: Array.from({ length: 11 }, () => googleLink("x")) })).status).toBe(422);
    expect((await send("/maps/nope/pins/link-preview", "POST", { urls: [googleLink("x")] })).status).toBe(404);
  });

  it("bulk: 항목마다 따로 — 만들어짐·중복·거절이 섞여도 200, 만들어진 핀마다 pin.created", async () => {
    const before = store.eventLog.length;
    const r = await send("/maps/map_1/pins/bulk", "POST", {
      pins: [
        { category: "카페", place_id: "kakao:mock-2", place_name: "해운대 바다 카페", lat: 35.1587, lng: 129.1604 },
        { category: "카페", place_id: "kakao:mock-2", place_name: "해운대 바다 카페", lat: 35.1587, lng: 129.1604 }, // 같은 요청 안의 중복
        { category: "숙소", place_id: "kakao:mock-4", place_name: "광안리 게스트하우스", lat: 35.1547, lng: 129.1191 },
        { source: "live", category: "음식점", kakao_place_id: "kakao:live-bulk", search_query: "곱창" },
      ],
    });
    expect(r.status).toBe(200);
    const { results } = await r.json();
    expect(results.map((x: { status: string }) => x.status)).toEqual(["created", "duplicate", "rejected", "created"]);
    expect(results[0].pin.place_name).toBe("해운대 바다 카페");
    expect(results[1].error).toMatchObject({ code: "PIN_DUPLICATE", detail: { pin_id: results[0].pin.id } });
    expect(results[2].error.code).toBe("PLACE_NOT_SUPPORTED");
    expect(store.eventLog.slice(before).filter((e) => e.type === "pin.created")).toHaveLength(2);
    expect((await send("/maps/map_1/pins/bulk", "POST", { pins: [] })).status).toBe(422);
    expect((await send("/maps/map_1/pins/bulk", "POST", { pins: Array.from({ length: 31 }, () => ({})) })).status).toBe(422);
  });
});

describe("#472 — 게스트 참여", () => {
  const send = (path: string, method: string, body?: unknown) =>
    fetch(`${BASE}${path}`, { method, ...(body ? { body: JSON.stringify(body) } : {}) });

  it("POST /auth/guest: 이름만으로 지도에 들어가 201, 이름이 비면 422, 모르는 토큰은 404", async () => {
    const { token } = await (await send("/maps/map_1/invite", "POST")).json();
    const before = store.members["map_1"].length;
    const r = await send("/auth/guest", "POST", { display_name: "  손님  ", invite_token: token });
    expect(r.status).toBe(201);
    const body = await r.json();
    expect(body.user).toMatchObject({ display_name: "손님", is_guest: true });
    expect(body.user.guest_invite_token).toBeUndefined(); // 서버 내부 값은 응답에 없다
    expect(body.map.id).toBe("map_1");
    expect(store.members["map_1"].length).toBe(before + 1);
    expect((await send("/auth/guest", "POST", { display_name: "   ", invite_token: token })).status).toBe(422);
    expect((await send("/auth/guest", "POST", { display_name: "손님", invite_token: "nope" })).status).toBe(404);
  });

  it("POST /auth/guest: 꺼진 토큰은 410, 토큰 하나당 게스트 10명 넘으면 409 GUEST_LIMIT", async () => {
    const { token } = await (await send("/maps/map_1/invite", "POST")).json();
    for (let i = 0; i < 10; i++) expect((await send("/auth/guest", "POST", { display_name: `g${i}`, invite_token: token })).status).toBe(201);
    const over = await send("/auth/guest", "POST", { display_name: "넘침", invite_token: token });
    expect(over.status).toBe(409);
    expect((await over.json()).code).toBe("GUEST_LIMIT");
    store.invites[token].revoked = true;
    expect((await send("/auth/guest", "POST", { display_name: "x", invite_token: token })).status).toBe(410);
  });

  it("게스트가 카카오로 전환하면(콜백) guest_merged=true로 돌아오고 더는 게스트가 아니다", async () => {
    resetScenario("guest");
    const res = await fetch(`${BASE}/auth/kakao/callback?code=x&state=y`, { redirect: "manual" });
    expect(res.status).toBe(302);
    expect(res.headers.get("location")).toBe("/?guest_merged=true");
    expect((await (await fetch(`${BASE}/auth/me`)).json()).is_guest).toBe(false);
    const again = await fetch(`${BASE}/auth/kakao/callback?code=x&state=y`, { redirect: "manual" });
    expect(again.headers.get("location")).toBe("/"); // 게스트가 아니면 쿼리가 붙지 않는다
    resetScenario("happy-path");
  });

  it("게스트 시나리오: 지도 만들기는 403 GUEST_NOT_ALLOWED, 그 밖의 구성원 행동은 된다", async () => {
    resetScenario("guest");
    expect((await (await fetch(`${BASE}/auth/me`)).json()).is_guest).toBe(true);
    const make = await send("/maps", "POST", { title: "새 지도", start_date: "2026-11-01", end_date: "2026-11-02" });
    expect(make.status).toBe(403);
    expect((await make.json()).code).toBe("GUEST_NOT_ALLOWED");
    expect((await fetch(`${BASE}/maps/map_1/pins`)).status).toBe(200);
    resetScenario("happy-path");
  });
});

describe("#470·#10 — 알림함·알림 설정, 서비스 피드백", () => {
  const send = (path: string, method: string, body?: unknown) =>
    fetch(`${BASE}${path}`, { method, ...(body ? { body: JSON.stringify(body) } : {}) });

  it("GET /me/notifications: 최근순, unread_count는 전체 기준, limit·before 커서, unread_only", async () => {
    const all = await (await fetch(`${BASE}/me/notifications`)).json();
    expect(all.items.map((n: { id: string }) => n.id)).toEqual(["ntf_1", "ntf_2"]);
    expect(all.unread_count).toBe(1);
    expect(all.next_before).toBeUndefined();
    const first = await (await fetch(`${BASE}/me/notifications?limit=1`)).json();
    expect(first.items).toHaveLength(1);
    expect(first.next_before).toBe("ntf_1");
    const next = await (await fetch(`${BASE}/me/notifications?limit=1&before=${first.next_before}`)).json();
    expect(next.items.map((n: { id: string }) => n.id)).toEqual(["ntf_2"]);
    expect(next.next_before).toBeUndefined();
    expect((await (await fetch(`${BASE}/me/notifications?unread_only=true`)).json()).items).toHaveLength(1);
    expect((await fetch(`${BASE}/me/notifications?limit=0`)).status).toBe(422);
  });

  it("POST /me/notifications/read: ids만 읽음, 모르는 id는 무시, 생략하면 전부, 100개 초과는 422", async () => {
    expect((await send("/me/notifications/read", "POST", { ids: ["ntf_1", "ntf_nope"] })).status).toBe(204);
    expect((await (await fetch(`${BASE}/me/notifications`)).json()).unread_count).toBe(0);
    store.notifications[1].read = false;
    expect((await send("/me/notifications/read", "POST")).status).toBe(204);
    expect(store.notifications.every((n) => n.read)).toBe(true);
    expect((await send("/me/notifications/read", "POST", { ids: Array.from({ length: 101 }, (_, i) => `n${i}`) })).status).toBe(422);
  });

  it("알림 설정: 종류 전부를 돌려주고 보낸 것만 바꾼다, 모르는 종류·빈 목록은 422", async () => {
    const prefs = await (await fetch(`${BASE}/me/notification-prefs`)).json();
    expect(prefs.prefs.map((p: { type: string }) => p.type)).toEqual(["pin_reaction", "member_joined", "owner_changed", "map_deleted", "my_ai_pin_published"]);
    expect(prefs.prefs.every((p: { enabled: boolean }) => p.enabled)).toBe(true);
    const put = await (await send("/me/notification-prefs", "PUT", { prefs: [{ type: "pin_reaction", enabled: false }] })).json();
    expect(put.prefs.find((p: { type: string }) => p.type === "pin_reaction").enabled).toBe(false);
    expect(put.prefs.find((p: { type: string }) => p.type === "member_joined").enabled).toBe(true);
    expect((await send("/me/notification-prefs", "PUT", { prefs: [{ type: "weekly_digest", enabled: true }] })).status).toBe(422);
    expect((await send("/me/notification-prefs", "PUT", { prefs: [] })).status).toBe(422);
  });

  it("POST /feedback: 201 + id, 공백뿐이면 422, 1000자 초과 422, 시간당 상한은 429", async () => {
    const ok = await send("/feedback", "POST", { message: "  지도가 느려요  ", category: "bug", map_id: "map_1" });
    expect(ok.status).toBe(201);
    expect(typeof (await ok.json()).id).toBe("string");
    expect(store.feedback[0]).toMatchObject({ message: "지도가 느려요", category: "bug" }); // 앞뒤 공백 제거
    expect((await send("/feedback", "POST", { message: "   " })).status).toBe(422);
    expect((await send("/feedback", "POST", { message: "가".repeat(1001) })).status).toBe(422);
    expect((await send("/feedback", "POST", { message: "x", category: "praise" })).status).toBe(422);
    for (let i = 0; i < 9; i++) await send("/feedback", "POST", { message: `m${i}` });
    expect((await send("/feedback", "POST", { message: "넘침" })).status).toBe(429);
  });
});

describe("#369 — 내 지도 상한(#433에서 20개)", () => {
  const create = () =>
    fetch(`${BASE}/maps`, { method: "POST", body: JSON.stringify({ title: "상한 시험", start_date: "2026-11-01", end_date: "2026-11-02" }) });

  it("내 지도가 상한이면 만들기가 409 MAP_LIMIT, 하나 지우면 다시 된다", async () => {
    expect(MAP_LIMIT).toBe(20);
    while ((await (await fetch(`${BASE}/maps`)).json()).items.length < MAP_LIMIT) expect((await create()).status).toBe(201);
    const r = await create();
    expect(r.status).toBe(409);
    expect(await r.json()).toMatchObject({ code: "MAP_LIMIT", detail: { limit: MAP_LIMIT, count: MAP_LIMIT } });
    const [last] = (await (await fetch(`${BASE}/maps`)).json()).items;
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

    const list = (await fetch(`${BASE}/maps`).then((r) => r.json())).items;
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

describe("#360 — 반응은 ♥/🚫 둘뿐, 추천은 ♥/🚫 의견이 달린 핀 1개부터 열린다", () => {
  it("△(neutral) 반응은 422 VALIDATION_ERROR", async () => {
    const res = await fetch(`${BASE}/pins/pin_1/reaction`, { method: "PUT", body: JSON.stringify({ type: "neutral" }) });
    expect(res.status).toBe(422);
    expect((await res.json()).code).toBe("VALIDATION_ERROR");
  });

  it("핀의 reaction_summary에는 like·against만 있다", async () => {
    const pins = await fetch(`${BASE}/maps/map_1/pins`).then((r) => r.json());
    for (const p of pins) expect(Object.keys(p.reaction_summary).sort()).toEqual(["against", "like"]);
  });

  it("준비 판정: 의견이 달린 핀 수 ≥ 1, required_count는 항상 1이고 구성원 수와 무관하다(혼자여도 같다)", async () => {
    store.members["map_1"] = store.members["map_1"].filter((m) => m.user_id === "u_me"); // 혼자
    const r = await fetch(`${BASE}/maps/map_1/recommend/readiness`).then((x) => x.json());
    expect(r["음식점"]).toMatchObject({ ready: true, required_count: 1 });
    expect(r["음식점"].answered_count).toBeGreaterThanOrEqual(1);
    expect(r["관광지"]).toMatchObject({ ready: false, answered_count: 0, required_count: 1 });
  });

  it("의견 핀이 없는 카테고리로 run을 만들면 409 NOT_READY", async () => {
    const res = await fetch(`${BASE}/maps/map_1/runs`, { method: "POST", body: JSON.stringify({ category: "관광지" }) });
    expect(res.status).toBe(409);
    expect((await res.json()).code).toBe("NOT_READY");
  });
});

describe("#340·회의 14번 — 지도 목록 구분과 후보 좌표", () => {
  it("내가 만든 지도는 my_role=owner, created_by_me=true", async () => {
    const maps = (await fetch(`${BASE}/maps`).then((r) => r.json())).items;
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

describe("#510 v2 계획 보조 에이전트 — 목 서버 계약", () => {
  it("바텀시트 상태: 기본 켜짐, 시드 제안 하나와 음식점 요약, 열람 전이라 점이 켜져 있다", async () => {
    const state = await fetch(`${BASE}/maps/map_1/agent`).then((r) => r.json());
    expect(state.settings).toMatchObject({ enabled: true, updated_by: null });
    expect(state.active_suggestion).toMatchObject({ id: "sug_1", diagnosis: "category_gap", category: "카페" });
    expect(state.has_unseen).toBe(true);
    expect(state.summaries[0].category).toBe("음식점");
    expect(state.summaries[0].not_filtered.notices[0]).toContain("가게에 직접 확인");
    expect(state.active_suggestion.claims).toBeUndefined(); // 서버 내부 값은 싣지 않는다
  });

  it("열람하면 점이 꺼지고, 열람은 멱등이다", async () => {
    for (let i = 0; i < 2; i++) {
      const r = await fetch(`${BASE}/agent/suggestions/sug_1/view`, { method: "POST" });
      expect(r.status).toBe(204);
    }
    const state = await fetch(`${BASE}/maps/map_1/agent`).then((r) => r.json());
    expect(state.has_unseen).toBe(false);
  });

  it("수락은 동작 설명만 돌려주고 agent.resolved를 낸다. 두 번째 처리는 409 SUGGESTION_RESOLVED", async () => {
    const res = await fetch(`${BASE}/agent/suggestions/sug_1/accept`, { method: "POST", body: JSON.stringify({ action_index: 0 }) });
    expect(res.status).toBe(200);
    expect((await res.json()).action).toMatchObject({ type: "open_recommend", params: { category: "카페" } });
    const ev = store.eventLog.at(-1)!;
    expect(ev).toMatchObject({ type: "agent.resolved", channel: "public", data: { suggestion_id: "sug_1", status: "accepted", resolved_action_type: "open_recommend" } });
    const again = await fetch(`${BASE}/agent/suggestions/sug_1/dismiss`, { method: "POST" });
    expect(again.status).toBe(409);
    expect((await again.json()).code).toBe("SUGGESTION_RESOLVED");
    const state = await fetch(`${BASE}/maps/map_1/agent`).then((r) => r.json());
    expect(state.active_suggestion).toBeNull();
  });

  it("범위 밖 action_index는 422", async () => {
    const res = await fetch(`${BASE}/agent/suggestions/sug_1/accept`, { method: "POST", body: JSON.stringify({ action_index: 9 }) });
    expect(res.status).toBe(422);
  });

  it("모드를 끄면 지금 제안이 무효화되고 settings_changed가 나간다", async () => {
    const res = await fetch(`${BASE}/maps/map_1/agent/settings`, { method: "PUT", body: JSON.stringify({ enabled: false }) });
    expect(await res.json()).toMatchObject({ enabled: false, updated_by: "u_me" });
    const types = store.eventLog.slice(-2).map((e) => e.type);
    expect(types).toEqual(["agent.resolved", "agent.settings_changed"]);
    const state = await fetch(`${BASE}/maps/map_1/agent`).then((r) => r.json());
    expect(state.active_suggestion).toBeNull();
    expect(state.has_unseen).toBe(false);
  });

  it("추천 막힘 조언: 결과가 적은 내 run은 200, 대상이 아니면 204, 남의 run은 403", async () => {
    resetScenario("no-results");
    const mine = await fetch(`${BASE}/runs/run_no_results/advice`);
    expect(mine.status).toBe(200);
    const advice = await mine.json();
    expect(advice).toMatchObject({ kind: "radius", actions: [{ type: "widen_radius" }] });
    // #717 — 문장은 조각 목록이다. 조언은 인용이 없어 text 조각만
    expect(advice.advice[0].segments[0]).toMatchObject({ kind: "text" });
    expect(advice.advice[0]).not.toHaveProperty("text");

    store.runAdvice["run_no_results"] = null;
    expect((await fetch(`${BASE}/runs/run_no_results/advice`)).status).toBe(204);

    store.runRequestedBy["run_no_results"] = "u_2";
    expect((await fetch(`${BASE}/runs/run_no_results/advice`)).status).toBe(403);
  });
});

describe("#623 지도 목록에 상한을 함께", () => {
  it("GET /maps는 {items, limit}이고 limit은 409 MAP_LIMIT의 detail.limit과 같다", async () => {
    const body = await (await fetch(`${BASE}/maps`)).json();
    expect(Array.isArray(body.items)).toBe(true);
    expect(body.limit).toBe(MAP_LIMIT);
  });
});

describe("#642 추천 탭 광고 — 목 서버 계약", () => {
  const JEJU = "lat=33.4996&lng=126.5312";

  it("카테고리와 반경으로 최대 2개를 고르고, 응답에 실린 광고만 노출 수가 오른다", async () => {
    const res = await fetch(`${BASE}/maps/map_1/ads?category=카페&${JEJU}`);
    expect(res.headers.get("Cache-Control")).toBe("no-store");
    const { ads } = await res.json();
    expect(ads.map((a: { ad_id: string }) => a.ad_id)).toEqual(["ad_1", "ad_2"]); // 반경 밖 ad_far, 음식점 ad_3은 빠짐
    expect(ads[0].place).toMatchObject({ place_id: "place_ad_cafe_1", category: "카페", lat: 33.5146 });
    expect(ads[0].memo).toBeUndefined();
    expect(store.adStats["ad_1"].served).toBe(1);
    expect(store.adStats["ad_3"]).toBeUndefined();
  });

  it("카테고리가 없으면 추천 대상 전체에서 고른다", async () => {
    const { ads } = await (await fetch(`${BASE}/maps/map_1/ads?${JEJU}`)).json();
    expect(ads.length).toBe(2);
  });

  it("추천 대상이 아닌 카테고리나 좌표가 없으면 422, 비구성원 지도면 404", async () => {
    expect((await fetch(`${BASE}/maps/map_1/ads?category=숙소&${JEJU}`)).status).toBe(422);
    expect((await fetch(`${BASE}/maps/map_1/ads?category=카페`)).status).toBe(422);
    expect((await fetch(`${BASE}/maps/no_such_map/ads?${JEJU}`)).status).toBe(404);
  });

  it("같은 장소의 핀이 이미 있으면 on_map=true", async () => {
    const pin = Object.values(store.pins).find((p) => p.map_id === "map_1")!;
    pin.place_name = "바다정원 카페";
    const { ads } = await (await fetch(`${BASE}/maps/map_1/ads?category=카페&${JEJU}`)).json();
    expect(ads.find((a: { ad_id: string }) => a.ad_id === "ad_1").on_map).toBe(true);
  });

  it("클릭 기록은 204, 없는 광고는 404, map_id가 없으면 422", async () => {
    const ok = await fetch(`${BASE}/ads/ad_1/clicks`, { method: "POST", body: JSON.stringify({ map_id: "map_1" }) });
    expect(ok.status).toBe(204);
    expect(store.adStats["ad_1"].clicks).toBe(1);
    expect((await fetch(`${BASE}/ads/nope/clicks`, { method: "POST", body: JSON.stringify({ map_id: "map_1" }) })).status).toBe(404);
    expect((await fetch(`${BASE}/ads/ad_1/clicks`, { method: "POST", body: JSON.stringify({}) })).status).toBe(422);
  });
});

describe("#334 AI 코스 짜기 — 목 서버 계약 (#580 결정 전 초안)", () => {
  const confirm = (pinId: string) =>
    fetch(`${BASE}/maps/map_1/shortlist`, { method: "POST", body: JSON.stringify({ pin_id: pinId }) });

  it("확정 장소가 2곳 미만이면 422 COURSE_NOT_ENOUGH_PLACES(detail에 min, count)", async () => {
    await confirm("pin_1");
    const res = await fetch(`${BASE}/maps/map_1/courses`, { method: "POST" });
    expect(res.status).toBe(422);
    const body = await res.json();
    expect(body.code).toBe("COURSE_NOT_ENOUGH_PLACES");
    expect(body.detail).toEqual({ min: 2, count: 1 });
  });

  it("요청 → 202, 첫 GET은 running(단계 2개), 다음 GET은 running(단계 5개), 그다음은 done, 확정 리스트가 바뀌면 stale", async () => {
    await confirm("pin_1");
    await confirm("pin_2");
    const created = await fetch(`${BASE}/maps/map_1/courses`, { method: "POST", body: JSON.stringify({ request_text: "하루에 덜 걷고 싶어요" }) });
    expect(created.status).toBe(202);
    const { course_run_id } = await created.json();

    // 진행 중인 run이 있으면 다시 요청할 수 없다
    const dup = await fetch(`${BASE}/maps/map_1/courses`, { method: "POST" });
    expect(dup.status).toBe(409);
    expect((await dup.json()).detail).toEqual({ course_run_id });

    const running = await (await fetch(`${BASE}/course-runs/${course_run_id}`)).json();
    expect(running.status).toBe("running");
    expect(running.days).toEqual([]);
    expect(running.outcome).toBeNull();
    expect(running.steps).toHaveLength(2);

    const running2 = await (await fetch(`${BASE}/course-runs/${course_run_id}`)).json();
    expect(running2.status).toBe("running");
    expect(running2.steps).toHaveLength(5);
    expect(running2.steps.slice(0, 2)).toEqual(running.steps); // 앞 단계는 그대로, 뒤로만 늘어난다
    expect(running2.days).toEqual([]);

    const done = await (await fetch(`${BASE}/course-runs/${course_run_id}`)).json();
    expect(done.status).toBe("done");
    expect(done.outcome).toBe("solved_with_checks");
    expect(done.goals[0].kind).toBe("daily_walk_low");
    const placed = done.days.flatMap((d: { slots: { pin_id: string }[] }) => d.slots.map((s) => s.pin_id));
    expect(placed.sort()).toEqual(["pin_1", "pin_2"]);
    expect(done.checks.length).toBe(2);
    expect(done.steps.length).toBe(7);
    expect(done.stale).toBe(false);

    await confirm("pin_3");
    const latest = await (await fetch(`${BASE}/maps/map_1/courses/latest`)).json();
    expect(latest.id).toBe(course_run_id);
    expect(latest.stale).toBe(true);
  });

  it("구간은 mode로 갈린다 — 2km 이하는 walk, 먼 구간은 transit(대중교통 약 분)", async () => {
    await confirm("pin_1");
    await confirm("pin_2");
    await confirm("pin_3");
    store.maps["map_1"].end_date = store.maps["map_1"].start_date; // 하루에 셋 — 구간이 둘 생긴다
    const items = store.shortlist["map_1"];
    items[0].pin.lat = 33.4996;
    items[0].pin.lng = 126.5312;
    items[1].pin.lat = 33.5015; // 첫째와 200m쯤
    items[1].pin.lng = 126.5312;
    items[2].pin.lat = 33.28; // 20km 넘게 떨어진 곳
    items[2].pin.lng = 126.7183;
    const { course_run_id } = await (await fetch(`${BASE}/maps/map_1/courses`, { method: "POST", body: JSON.stringify({}) })).json();
    await fetch(`${BASE}/course-runs/${course_run_id}`);
    await fetch(`${BASE}/course-runs/${course_run_id}`);
    const done = await (await fetch(`${BASE}/course-runs/${course_run_id}`)).json();
    const legs = done.days.flatMap((d: { legs: { mode: string; approx_minutes: number }[] }) => d.legs);
    expect(legs.length).toBeGreaterThan(0);
    for (const l of legs) expect(["walk", "transit"]).toContain(l.mode);
    const transit = legs.filter((l: { mode: string }) => l.mode === "transit");
    expect(transit.length).toBeGreaterThan(0);
    expect(transit[0].approx_minutes).toBeGreaterThan(10); // 대기 10분이 더해진 대략 분
    expect(done.steps.some((st: { text: string }) => st.text.includes("대중교통 1구간"))).toBe(true);
  });

  it("짠 적이 없으면 latest는 204, 없는 run은 404, 지도가 없으면 404", async () => {
    expect((await fetch(`${BASE}/maps/map_1/courses/latest`)).status).toBe(204);
    expect((await fetch(`${BASE}/course-runs/nope`)).status).toBe(404);
    expect((await fetch(`${BASE}/maps/no_such_map/courses`, { method: "POST" })).status).toBe(404);
  });

  it("하루 5번을 넘기면 429 COURSE_LIMIT", async () => {
    await confirm("pin_1");
    await confirm("pin_2");
    for (let i = 0; i < 5; i += 1) {
      const res = await fetch(`${BASE}/maps/map_1/courses`, { method: "POST" });
      expect(res.status).toBe(202);
      const { course_run_id } = await res.json();
      await fetch(`${BASE}/course-runs/${course_run_id}`); // running(2)
      await fetch(`${BASE}/course-runs/${course_run_id}`); // running(5)
      await fetch(`${BASE}/course-runs/${course_run_id}`); // done
    }
    const res = await fetch(`${BASE}/maps/map_1/courses`, { method: "POST" });
    expect(res.status).toBe(429);
    expect((await res.json()).detail).toEqual({ limit: 5, used: 5 });
  });
});
