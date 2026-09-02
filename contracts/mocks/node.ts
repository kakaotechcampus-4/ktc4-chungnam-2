/**
 * FE 테스트 코드(Vitest/Jest 등)에서 사용. 예:
 *   import { server } from "@pingo/contracts/mocks/node";
 *   beforeAll(() => server.listen());
 *   afterEach(() => { server.resetHandlers(); resetScenario("happy-path"); });
 *   afterAll(() => server.close());
 */
import { setupServer } from "msw/node";
import { handlers } from "./handlers";
import { loadDefaultScenario } from "./scenarios";

loadDefaultScenario();

export const server = setupServer(...handlers);
export { resetScenario, type ScenarioName } from "./scenarios";
