// 정예 장소와 사용자 둘을 시드하고 세션 쿠키를 E2E_USERS로 넘긴다(#1281). 여기서 정한 환경 변수는 테스트 워커가 물려받는다.
import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { backendEnv } from './playwright.config'

export default function globalSetup() {
  const here = path.dirname(fileURLToPath(import.meta.url))
  const out = execFileSync(process.env.E2E_PYTHON ?? 'python', [path.join(here, 'seed.py')], {
    cwd: path.join(here, '../backend'),
    env: { ...process.env, ...backendEnv },
    encoding: 'utf8',
  })
  process.env.E2E_USERS = out.trim().split('\n').at(-1)
}
