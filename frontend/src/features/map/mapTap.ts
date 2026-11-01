/**
 * 지도 빈 곳을 눌렀을 때 할 일(#1028, 멘토 리뷰 #816). 어느 탭이든 같다 — 지도는 둘러보는 데 쓰는 사람이 많아서,
 * 누르자마자 검색이 뜨면 뜻밖이다. 근처 장소 찾기는 말풍선을 한 번 더 눌러야 한다.
 * - release: 고른 것(핀 상세·검색 결과·AI 후보)이 있으면 푼다
 * - close: 말풍선이 떠 있으면 닫는다(다른 곳을 누름)
 * - open: 누른 자리에 「이 근처 장소 찾기」 말풍선을 띄운다
 * - none: 누른 자리를 모른다
 */
export type MapTapAction = 'release' | 'close' | 'open' | 'none'

export function mapTapAction({ selected, bubbleOpen, at }: { selected: boolean; bubbleOpen: boolean; at: unknown }): MapTapAction {
  if (selected) return 'release'
  if (bubbleOpen) return 'close'
  return at ? 'open' : 'none'
}
