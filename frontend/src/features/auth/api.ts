import { api, ApiError } from '@/api'

import type { UserDto } from './model'

export const fetchMe = () => api<UserDto>('/auth/me')

export function isUnauthorized(err: unknown) {
  return err instanceof ApiError && err.status === 401
}

/**
 * 로그인 시작 주소(#128). BE 가 state 를 쿠키에 심고 카카오 인가 화면으로 보낸다 — 프론트는 이동만 한다(fetch 아님).
 * 목 서버 모드에선 msw 가 페이지 이동을 가로채지 못하므로, 목 핸들러(/auth/kakao/login → /)와 같은 곳으로 바로 보낸다.
 */
export function kakaoLoginUrl(): string {
  const base = import.meta.env.VITE_API_BASE_URL
  return base ? `${base}/auth/kakao/login` : '/'
}
