/**
 * 지도 핀 모양 — 둥근 머리 + 곧은 옆선(#1355). 머리 가운데 (12,10)·반지름 8이고, 뾰족한 끝(12,30)이 좌표라 오버레이 yAnchor 는 1이다.
 * 지도 핀(pinMarker)·온보딩 그림(WelcomeScene)·로그인 지도 그림(MapIllustration)이 같이 쓴다. viewBox 0 0 24 32 기준.
 */
export const PIN_PATH = 'M12 30L4.67 13.2A8 8 0 1 1 19.33 13.2Z'

/**
 * 핀 윤곽선 굵기(viewBox 24 기준). 일반 핀(`--pin-outline`)과 확정 핀(`--pin-confirmed-mark`)이 같은 굵기의 진한 윤곽선이다 —
 * 일반 핀을 빨강 2.5 테두리로 두면 참여 100%에서 속과 같은 색이라 테두리가 사라져 확정 핀과 다른 모양처럼 보였다.
 */
export const PIN_OUTLINE = 1.5
