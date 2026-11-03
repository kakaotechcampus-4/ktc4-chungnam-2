// 핵심 흐름 브라우저 E2E(#1281). 실제 백엔드와 실제 화면 빌드를 띄워 Chromium으로 돈다. 로컬 실행법은 qa/README.md.
// - 백엔드: 마이그레이션 뒤 uvicorn. 장소는 자체 DB만(PLACES_MODE=real, 외부 소스 없음 — 시드한 정예), 모델은 스텁(LLM_MODE=dev).
//   개발자 .env(실제 키)를 읽지 않는다(PINGO_LOAD_DOTENV=0).
// - 화면: 이 백엔드를 보도록 빌드해 preview로 띄운다. 카카오 지도 키는 비운다 — 지도 없이 목록과 시트로 흐름이 이어진다.
// - webServer가 globalSetup보다 먼저 돈다. 그래서 마이그레이션은 백엔드 명령에, 시드는 global-setup.ts에 둔다.
import { defineConfig, devices } from '@playwright/test'

export const API_URL = 'http://localhost:8010'
export const WEB_URL = 'http://localhost:4173'

const python = process.env.E2E_PYTHON ?? 'python'

export const backendEnv: Record<string, string> = {
  PINGO_LOAD_DOTENV: '0',
  PINGO_ENV: 'dev',
  PLACES_MODE: 'real',
  PLACES_SOURCES: '',
  LLM_MODE: 'dev',
  DATABASE_URL: process.env.DATABASE_URL ?? 'postgresql://pingo:pingo@localhost:5432/pingo_e2e',
  FRONTEND_BASE_URL: WEB_URL,
  PYTHONUTF8: '1',
}

export default defineConfig({
  testDir: './tests',
  globalSetup: './global-setup.ts',
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 90_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: WEB_URL,
    locale: 'ko-KR',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  // 사용자 대부분이 휴대폰으로 쓴다(frontend/PRODUCT.md) — 휴대폰 폭으로 돈다
  projects: [{ name: 'mobile-chromium', use: { ...devices['Pixel 7'] } }],
  webServer: [
    {
      command: `"${python}" -m alembic upgrade head && "${python}" -m uvicorn main:asgi_app --port 8010`,
      cwd: '../backend',
      url: `${API_URL}/health`,
      env: backendEnv,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
    },
    {
      command: 'npx vite build && npx vite preview --port 4173 --strictPort',
      cwd: '../frontend',
      url: WEB_URL,
      env: { VITE_API_BASE_URL: API_URL, VITE_KAKAO_MAP_KEY: '' },
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
    },
  ],
})
