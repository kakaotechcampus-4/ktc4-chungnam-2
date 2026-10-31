import { api, ApiError } from '@/api'

import type { PendingAccountDto, PendingChoice, UserDto } from './model'

export const fetchMe = () => api<UserDto>('/auth/me')

export function isUnauthorized(err: unknown) {
  return err instanceof ApiError && err.status === 401
}

/**
 * 탈퇴 계정 재로그인의 선택 안내와 선택(#855). 세션이 아니라 콜백이 내린 `pending_account` 쿠키(10분)로 부른다.
 * 선택은 JSON 본문으로만 보낸다 — `api()` 가 본문이 있으면 Content-Type 을 붙인다.
 */
export const fetchPendingAccount = () => api<PendingAccountDto>('/auth/pending')

export const choosePendingAccount = (choice: PendingChoice) =>
  api<UserDto>('/auth/pending', { method: 'POST', body: JSON.stringify({ choice }) })

/** 쿠키가 없거나 만료·이미 선택됨 — 고를 게 없으니 카카오로 다시 시작한다. */
export function isNoPendingLogin(err: unknown) {
  return err instanceof ApiError && err.code === 'NO_PENDING_LOGIN'
}

/**
 * 로그인 시작 주소(#128). BE 가 state 를 쿠키에 심고 카카오 인가 화면으로 보낸다 — 프론트는 이동만 한다(fetch 아님).
 * 목 서버 모드에선 msw 가 페이지 이동을 가로채지 못하므로, 목 핸들러(/auth/kakao/login → /)와 같은 곳으로 바로 보낸다.
 */
export function kakaoLoginUrl(): string {
  const base = import.meta.env.VITE_API_BASE_URL
  return base ? `${base}/auth/kakao/login` : '/'
}

export const logout = () => api<void>('/auth/logout', { method: 'POST' })

/** 회원 탈퇴(#155). 반응·사유는 지워지고 찍은 핀은 '탈퇴한 구성원'의 이름으로 남는다. */
export const withdraw = () => api<void>('/auth/withdraw', { method: 'POST' })
