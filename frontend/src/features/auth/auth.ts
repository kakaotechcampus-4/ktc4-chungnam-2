import { useQuery } from '@tanstack/react-query'
import type { components } from '@pingo/contracts/src/types/api'

import { api, ApiError } from '@/api'

export type User = components['schemas']['User']

/** 로그인 여부의 정본. 쿠키는 httpOnly 라 프론트가 직접 볼 수 없고, 이 응답이 401 이면 비로그인이다. */
export function useMe() {
  return useQuery({
    queryKey: ['me'],
    queryFn: () => api<User>('/auth/me'),
    // 401 은 다시 물어도 401 이다.
    retry: (count, err) => !(err instanceof ApiError && err.status === 401) && count < 1,
  })
}

export function isUnauthorized(err: unknown) {
  return err instanceof ApiError && err.status === 401
}

/**
 * 카카오 인가 화면 주소. 카카오가 BE 콜백(/auth/kakao/callback)으로 code 를 넘기고,
 * BE 가 쿠키를 심은 뒤 FRONTEND_LOGIN_REDIRECT_URL 로 돌려보낸다.
 * redirect_uri 는 BE 의 KAKAO_REDIRECT_URI 와 글자까지 같아야 한다.
 */
export function kakaoLoginUrl(): string | null {
  const clientId = import.meta.env.VITE_KAKAO_REST_KEY
  const base = import.meta.env.VITE_API_BASE_URL
  if (!clientId || !base) return null
  const q = new URLSearchParams({
    response_type: 'code',
    client_id: clientId,
    redirect_uri: `${base}/auth/kakao/callback`,
  })
  return `https://kauth.kakao.com/oauth/authorize?${q}`
}

/**
 * BE 콜백은 로그인 후 항상 같은 주소로 돌려보낸다(원래 가려던 곳을 기억하지 않는다).
 * 초대 링크로 들어와 로그인한 사람을 그 초대로 되돌리려고 토큰을 잠깐 들고 있는다.
 * 저장소가 막힌 브라우저에선 되돌리기만 빠지고 로그인은 그대로 된다.
 */
const PENDING_INVITE = 'pendingInvite'

export function savePendingInvite(token: string) {
  try {
    sessionStorage.setItem(PENDING_INVITE, token)
  } catch {
    // 위 주석 — 되돌리기만 포기한다
  }
}

export function readPendingInvite(): string | null {
  try {
    return sessionStorage.getItem(PENDING_INVITE)
  } catch {
    return null
  }
}

/** 초대 화면에 도착하면 지운다 — 그래야 목록으로 돌아왔을 때 다시 끌려가지 않는다. */
export function clearPendingInvite() {
  try {
    sessionStorage.removeItem(PENDING_INVITE)
  } catch {
    // 읽기도 막혔을 테니 남을 것도 없다
  }
}
