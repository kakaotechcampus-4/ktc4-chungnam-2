import type { components } from '@pingo/contracts/src/types/api'

type ErrorBody = components['schemas']['Error']

/**
 * docs/errors.md 의 공통 봉투 `{ code, message, detail? }` 를 그대로 들고 있는 에러.
 * 화면은 `code` 로 분기한다 (NO_RESULTS / NOT_READY / EVIDENCE_REQUIRED …).
 * HTTP status 로 분기하지 않는다 — 같은 409 에 NOT_READY·PIN_DUPLICATE·REGION_CONFLICT 가 겹친다.
 */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly detail?: Record<string, unknown>

  constructor(status: number, body: ErrorBody) {
    super(body.message)
    this.name = 'ApiError'
    this.status = status
    this.code = body.code
    this.detail = body.detail
  }
}

/** 채우면 실제 BE 로 간다. 비워두면 상대경로 — 목 서버가 와일드카드 오리진으로 잡는다. */
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

/**
 * BASE_URL 이 비었을 때만 목 서버를 켠다. 실제 BE 와 통합할 땐 BASE_URL 만 채우면 된다.
 * 쓰는 쪽에서 `import.meta.env.DEV &&` 를 앞에 붙인다 — 그래야 프로덕션 번들에서 msw 가 잘려 나간다.
 */
export const USE_MOCK = !BASE_URL

async function toApiError(res: Response): Promise<ApiError> {
  try {
    const body = (await res.json()) as ErrorBody
    if (typeof body?.code === 'string') return new ApiError(res.status, body)
  } catch {
    // 아래로 떨어진다
  }
  // 공통 봉투가 아닌 응답 = 앱 레벨이 아니라 인프라 레벨 실패(프록시·게이트웨이 등).
  // 조용히 삼키지 않고 카탈로그의 전역 코드로 세워서 올린다.
  return new ApiError(res.status, {
    code: 'INTERNAL_ERROR',
    message: `서버 응답을 해석할 수 없어요 (HTTP ${res.status})`,
  })
}

/**
 * 프로젝트의 유일한 HTTP 진입점.
 * `credentials: 'include'` 고정 — 인증은 httpOnly 쿠키이고 토큰을 프론트에 두지 않는다
 * (최종기획안 13절, api-spec.yaml 의 전역 cookieAuth).
 */
async function request(path: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    credentials: 'include',
    headers: {
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  })
  if (!res.ok) throw await toApiError(res)
  return res
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await request(path, init)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

/**
 * JSON 이 아니라 파일로 오는 응답(확정 리스트 내보내기 #484). 이름은 서버의 Content-Disposition 을 따른다.
 * 서버가 다른 오리진이면 브라우저가 이 헤더를 가려서(CORS expose 없음) 이름이 없을 수 있다 — 부르는 쪽이 기본 이름을 둔다.
 */
export async function apiFile(path: string): Promise<{ blob: Blob; filename?: string }> {
  const res = await request(path)
  return { blob: await res.blob(), filename: filenameFrom(res.headers.get('Content-Disposition')) }
}

/** `filename*=UTF-8''<퍼센트 인코딩>`(RFC 5987)을 먼저, 없으면 `filename="..."`. */
export function filenameFrom(disposition: string | null): string | undefined {
  if (!disposition) return undefined
  const star = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (star) {
    try {
      return decodeURIComponent(star[1].trim())
    } catch {
      // 잘못 인코딩된 이름은 아래 ASCII 이름으로 떨어진다.
    }
  }
  return /filename="?([^";]+)"?/i.exec(disposition)?.[1]
}
