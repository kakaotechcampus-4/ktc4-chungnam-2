/** 단순화 로고 도형(32×32). 지도의 AI 후보 핀(pinMarker)도 이 값으로 얼굴을 그린다. */
export const PINGO_MARK = {
  pin: 'M16 10.5C13.9 8.6 13 7.3 13 6A3 3 0 0 1 19 6C19 7.3 18.1 8.6 16 10.5Z',
  hole: { cx: 16, cy: 6, r: 1.1 },
  face: { x: 5, y: 11.5, w: 22, h: 17, rx: 7 },
  eyes: [
    { cx: 12.5, cy: 20, rx: 1.3, ry: 1.9 },
    { cx: 19.5, cy: 20, rx: 1.3, ry: 1.9 },
  ],
} as const
