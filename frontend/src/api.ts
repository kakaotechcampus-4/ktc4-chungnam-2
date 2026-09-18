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

/** 배포 환경에서만 채운다. 비워두면 상대경로 — 목 서버가 와일드카드 오리진으로 잡는다. */
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

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
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    credentials: 'include',
    headers: {
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  })

  if (!res.ok) throw await toApiError(res)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}
