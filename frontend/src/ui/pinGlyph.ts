import { LIKE_PATH } from './Mark'
import { PIN_OUTLINE, PIN_PATH } from './pinPath'
import { PINGO_MARK } from './pingoMark'

/** 핑고 얼굴(32×32 로고)을 핀 머리(가운데 12,10) 안에 넣는 변환. */
const MARK_IN_HEAD = 'translate(5.3 3.6) scale(0.42)'

export type PinGlyph =
  /** 일반 핀(올린 AI 추천 핀 포함). ratio 는 참여율 0~1. */
  | { kind: 'normal'; ratio: number }
  /** 확정 핀. order 가 있으면 ♥ 대신 순서 번호를 쓴다(온보딩의 동선 장면). */
  | { kind: 'confirmed'; order?: number }
  /** 올리기 전 AI 후보(핑고 핀). */
  | { kind: 'candidate' }

/**
 * 지도 핀 한 개의 SVG 속(viewBox 0 0 24 32). 지도 핀(`features/map/pinMarker`)과 핀이 나오는 그림
 * (온보딩 `WelcomeScene`, 로그인 `MapIllustration`, 지역 `RegionCover`)이 이 함수 하나로 그린다 —
 * 그림마다 핀을 따로 적었더니 점선 AI 핀·점 없는 일반 핀처럼 옛 모양이 남았다(#1550).
 * - 일반: 진한 빨강 윤곽선(`--pin-outline`) + 속은 참여율만큼 회색→빨강(oklch 로 섞어야 중간이 탁해지지 않는다) + 머리 가운데 진한 빨간 점.
 *   빨강 테두리였을 땐 참여 100%에서 속과 같은 색이라 테두리가 사라졌다(#1519). AI 추천도 「지도에 올리기」 뒤엔 이 모양이다(#1032).
 * - 확정: 골드 채움 + 갈색 윤곽선 + 진한 빨강 하트(좋음 하트 `LIKE_PATH`를 0.6배로). 참여율과 무관하다. 흰 테두리는 없앴다(#1355) —
 *   골드는 어두운 타일에서도 밝고, 밝은 땅 위는 갈색 윤곽선이 가른다(#299). 하트는 색을 못 가르는 사람에게 확정을 알린다(흑백이면 참여 50% 핀과 밝기가 같다).
 * - AI 후보: brand-600 핀 + 흰 테두리 + 머리에 흰 핑고 얼굴(하단 AI 탭 활성 모양과 같은 「파랑 채움 + 흰 얼굴」, #843).
 * 윤곽선 굵기는 일반·확정이 같다(`PIN_OUTLINE`). var()·color-mix() 는 SVG 속성보다 style 에서 확실히 해석된다.
 * 넣는 값은 상수와 숫자뿐이라 마크업으로 넣어도 된다 — 장소 이름 같은 사용자 글은 여기 들어오지 않는다.
 */
export function pinGlyph(g: PinGlyph): string {
  if (g.kind === 'candidate') {
    const { pin, hole, face, eyes } = PINGO_MARK
    return `<path d="${PIN_PATH}" stroke-linejoin="round" style="fill:var(--brand-600);stroke:#fff;stroke-width:2" />
      <g transform="${MARK_IN_HEAD}">
        <path d="${pin}" fill="#fff" />
        <circle cx="${hole.cx}" cy="${hole.cy}" r="${hole.r}" style="fill:var(--brand-600)" />
        <rect x="${face.x}" y="${face.y}" width="${face.w}" height="${face.h}" rx="${face.rx}" fill="#fff" />
        ${eyes.map((e) => `<ellipse cx="${e.cx}" cy="${e.cy}" rx="${e.rx}" ry="${e.ry}" style="fill:var(--ink-900)" />`).join('')}
      </g>`
  }
  if (g.kind === 'confirmed') {
    const mark =
      g.order != null
        ? `<text x="12" y="13.5" text-anchor="middle" style="font:700 10px var(--font-sans);fill:var(--pin-confirmed-mark)">${Math.trunc(g.order)}</text>`
        : `<path d="${LIKE_PATH}" transform="translate(7.2 5.7) scale(.6)" style="fill:var(--pin-confirmed-heart)" />`
    return `<path d="${PIN_PATH}" stroke-linejoin="round" style="fill:var(--pin-confirmed);stroke:var(--pin-confirmed-mark);stroke-width:${PIN_OUTLINE}" />${mark}`
  }
  const fill = `color-mix(in oklch, var(--pin-fill-full) ${Math.round(g.ratio * 100)}%, var(--pin-fill-empty))`
  return `<path d="${PIN_PATH}" stroke-linejoin="round" style="fill:${fill};stroke:var(--pin-outline);stroke-width:${PIN_OUTLINE}" />
      <circle cx="12" cy="10" r="3.2" style="fill:var(--pin-dot)" />`
}
