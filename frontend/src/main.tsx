import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'

import App from '@/App'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // 인증 실패·권한 없음·형식 오류는 다시 던져도 같은 답이 온다. 재시도는 한 번만.
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

/**
 * contracts/README.md §2 — 백엔드 없이 전 화면을 돌리는 목 서버.
 * 실제 BE 가 붙으면 이 함수만 지우면 된다.
 */
async function enableMocking() {
  if (!import.meta.env.DEV) return
  const { worker } = await import('@pingo/contracts/mocks/browser')
  await worker.start({ onUnhandledRequest: 'bypass' })
}

function render() {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <App />
        {import.meta.env.DEV && <ReactQueryDevtools initialIsOpen={false} />}
      </QueryClientProvider>
    </StrictMode>,
  )
}

enableMocking()
  .catch((err) => {
    // 조용히 넘어가지 않는다. 워커가 안 뜨면 모든 요청이 실패하므로 원인을 먼저 보여준다.
    console.error('[msw] 목 서버 시작 실패 — public/mockServiceWorker.js 확인', err)
  })
  .finally(render)
