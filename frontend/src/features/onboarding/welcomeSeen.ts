/**
 * 첫 로그인 온보딩(`/welcome`)을 이 기기에서 봤는지. 서버에는 남기지 않아 다른 기기에선 한 번 더 뜬다.
 * 저장소가 막힌 브라우저에선 본 것으로 친다 — 기억할 수 없으니 목록에 올 때마다 다시 뜨지 않게.
 */
const WELCOME_SEEN = 'welcomeSeen'

export function hasSeenWelcome(): boolean {
  try {
    return localStorage.getItem(WELCOME_SEEN) === '1'
  } catch {
    return true
  }
}

export function markWelcomeSeen() {
  try {
    localStorage.setItem(WELCOME_SEEN, '1')
  } catch {
    // 위 주석 — 읽기도 막혔을 테니 다시 뜨지 않는다
  }
}
