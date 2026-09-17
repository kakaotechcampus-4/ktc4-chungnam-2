import path from 'node:path'
import { fileURLToPath } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const rootDir = path.dirname(fileURLToPath(import.meta.url))
const contractsDir = path.resolve(rootDir, '../contracts')

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      // 매칭 규칙이 "완전일치 또는 find + '/' 접두"라 서로 충돌하지 않는다.
      // '@' 는 '@/...' 만, '@pingo/contracts' 는 '@pingo/contracts/...' 만 잡는다.
      '@': path.resolve(rootDir, 'src'),
      // contracts 를 node_modules 밖 절대경로로 돌려서 Vite 가 "소스"로 취급하게 만든다.
      // 그래야 .ts 를 esbuild 로 변환한다 (file: 의존성이 깨지는 이유의 정확한 반대).
      '@pingo/contracts': contractsDir,
    },
    // contracts/node_modules 가 없어서 contracts 내부의 bare `import "msw"` 가
    // frontend/node_modules 까지 올라오지 못한다. dedupe 가 프로젝트 root 기준 해석을 강제한다.
    dedupe: ['react', 'react-dom', 'msw'],
  },
  server: {
    // contracts/ 는 Vite root(frontend/) 바깥이다. 명시하지 않으면 빌드는 되는데 dev 에서 403.
    fs: { allow: [rootDir, contractsDir] },
  },
  optimizeDeps: {
    // 목 레이어가 dynamic import 로만 들어와서 스캐너가 놓친다. 미리 넣지 않으면 첫 렌더 직후
    // "new dependencies optimized" full reload 가 걸리고 그 순간 워커가 잠깐 죽는다.
    include: ['msw', 'msw/browser'],
  },
})
