/**
 * FE 앱(브라우저)에서 사용. 예:
 *   import { worker } from "@pingo/contracts/mocks/browser";
 *   await worker.start();
 */
import { setupWorker } from "msw/browser";
import { handlers } from "./handlers";
import { loadDefaultScenario } from "./scenarios";

loadDefaultScenario();

export const worker = setupWorker(...handlers);
export { resetScenario, type ScenarioName } from "./scenarios";
