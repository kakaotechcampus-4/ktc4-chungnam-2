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
