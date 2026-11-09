import { showToast } from '@/features/shell/toast'

/**
 * 지도 빈 곳을 눌렀을 때 할 일(#1028, 멘토 리뷰 #816). 어느 탭이든 같다 — 지도는 둘러보는 데 쓰는 사람이 많아서,
 * 누르자마자 검색이 뜨면 뜻밖이다. 「신규 핀 찍기」는 말풍선을 한 번 더 눌러야 한다(#1549).
 * - release: 고른 것(핀 상세·검색 결과·AI 후보)이 있으면 푼다
 * - close: 말풍선이 떠 있으면 닫는다(다른 곳을 누름)
 * - open: 누른 자리에 「신규 핀 찍기」 말풍선을 띄운다
 * - none: 누른 자리를 모른다
 */
export type MapTapAction = 'release' | 'close' | 'open' | 'none'

export function mapTapAction({ selected, bubbleOpen, at }: { selected: boolean; bubbleOpen: boolean; at: unknown }): MapTapAction {
  if (selected) return 'release'
  if (bubbleOpen) return 'close'
  return at ? 'open' : 'none'
}

const HINT_KEY = 'mapMenuHintSeen'

/**
 * 처음 한 번, 말풍선을 연 김에 빠른 길을 알린다(#1549) — PC는 우클릭, 터치는 길게 누르기.
 * 이 브라우저에만 기억한다. 저장소를 못 쓰면(사생활 보호 창) 매번 알리지 않도록 아예 띄우지 않는다.
 */
export function showMapMenuHintOnce() {
  try {
    if (localStorage.getItem(HINT_KEY)) return
    localStorage.setItem(HINT_KEY, '1')
  } catch {
    return
  }
  const fine = window.matchMedia?.('(pointer: fine)').matches
  showToast(fine ? '지도를 우클릭하면 핀을 찍을 수 있어요' : '지도를 길게 누르면 핀을 찍을 수 있어요')
}
