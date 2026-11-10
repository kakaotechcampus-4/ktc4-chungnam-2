import { showToast } from '@/features/shell/toast'

/**
 * 지도 빈 곳을 눌렀을 때 할 일(#1028, 멘토 리뷰 #816). 어느 탭이든 같다 — 지도는 둘러보는 데 쓰는 사람이 많아서,
 * 누르면 그 자리를 보러 가는 것이 뜻밖이 아니다. 「신규 핀 찍기」는 우클릭·길게 누르기로만 연다(#1549, #1613).
 * - release: 고른 것(핀 상세·검색 결과·AI 후보)이 있으면 푼다(지도는 그대로)
 * - close: 메뉴가 떠 있으면 닫는다(지도는 그대로)
 * - center: 누른 자리를 보이는 영역 가운데로 옮긴다
 * - none: 누른 자리를 모른다
 */
export type MapTapAction = 'release' | 'close' | 'center' | 'none'

export function mapTapAction({ selected, bubbleOpen, at }: { selected: boolean; bubbleOpen: boolean; at: unknown }): MapTapAction {
  if (selected) return 'release'
  if (bubbleOpen) return 'close'
  return at ? 'center' : 'none'
}

const HINT_KEY = 'mapMenuHintSeen'

/**
 * 처음 한 번, 빈 곳을 누른 김에 핀 찍는 길을 알린다(#1549, #1613) — PC는 우클릭, 터치는 길게 누르기.
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
