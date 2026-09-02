import { afterAll, beforeAll, afterEach, describe, expect, it } from "vitest";
import { server } from "./node";
import { resetScenario } from "./scenarios";

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

    const routes = await fetch(`${BASE}/maps/map_1/route`).then((r) => r.json());
    expect(routes.length).toBe(1);
    expect(routes[0].legs.length).toBe(1);
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

  it("retry-limit — 3회 초과 시 429 RETRY_LIMIT", async () => {
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
      body: JSON.stringify({ category: "음식점", place_id: "dup-1" }),
    });
    expect(res.status).toBe(201);
    const res2 = await fetch(`${BASE}/maps/map_1/pins`, {
      method: "POST",
      body: JSON.stringify({ category: "음식점", place_id: "dup-1" }),
    });
    expect(res2.status).toBe(409);
  });
});
