/** 셸 부품들이 서로 맞물리는 치수. 토스트가 지도 버튼과의 겹침을 계산할 때도 쓴다. */

/** 하단 탭 바 높이. 시트는 그 위에서 멈춘다. */
export const TAB_BAR_H = 74

/** 지도 버튼 한 변 44px(터치 최소), 화면 오른쪽 여백 16px, 세 개를 쌓은 높이 + 시트와의 틈. */
export const CONTROLS = { size: 44, right: 16, stackHeight: 44 * 3 + 12 }

/**
 * 넓은 화면의 왼쪽 패널 폭(#351·#338). 패널은 화면 전체에 깔린 지도 위에 뜬 카드다(#1538, 카카오맵처럼).
 * 탭은 패널 머리 안에 있어서 접으면 지도를 가리는 게 없다.
 * 태블릿은 408 → 360(모바일이 맞춰 둔 가장 좁은 폭)으로 줄여 지도 몫을 늘린다(#603).
 */
export const PANEL_W = { pc: 408, tablet: 360 }

/** 떠 있는 패널 카드(왼쪽 패널, 「일정 짜기」)와 화면 가장자리·서로 사이의 틈. */
export const PANEL_GAP = 12

/** 넓은 화면에서 지도 왼쪽을 가리는 폭 — 열린 카드들의 오른쪽 끝. 지도 위 칩·버튼과 지도 카메라가 이 폭만큼 비킨다. */
export function panelCover(panelOpen: boolean, panelW: number, sideOpen: boolean) {
  const left = panelOpen ? PANEL_GAP + panelW : 0
  return sideOpen ? left + PANEL_GAP + SIDE_PANEL_W : left
}

/** 내용 패널 옆에 붙는 패널(확정 탭 「일정 짜기」, `SidePanel`) 폭. 열려 있으면 지도 위 토스트·버튼이 그만큼 오른쪽으로 비킨다. */
export const SIDE_PANEL_W = 360
