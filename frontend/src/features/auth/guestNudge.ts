import { showToast } from '@/features/shell/toast'

import { kakaoLoginUrl } from './api'

/**
 * 게스트가 첫 의견을 남긴 직후 한 번만 카카오 로그인을 권한다(기획안 11절 게스트 참여, #485).
 * 게스트는 그 브라우저에만 있는 계정이라 「한 번」도 이 브라우저 기준이다. 저장소가 막혔으면 권하지 않는다 — 기억할 수 없어 의견마다 뜨게 된다.
 */
const GUEST_NUDGED = 'guestLoginNudged'
export const GUEST_NUDGE_TEXT = '게스트 기록은 이 브라우저에만 남아요. 카카오로 로그인하면 어디서든 이어져요'

export function nudgeGuestOnce(isGuest: boolean | undefined) {
  if (!isGuest) return
  try {
    if (localStorage.getItem(GUEST_NUDGED) === '1') return
    localStorage.setItem(GUEST_NUDGED, '1')
  } catch {
    return
  }
  showToast(GUEST_NUDGE_TEXT, { label: '카카오로 로그인', onClick: () => window.location.assign(kakaoLoginUrl()) })
}
