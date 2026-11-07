import type { ReactNode } from 'react'

/**
 * 핑고 마크 — 화면 글 옆에 붙는 기호(좋음·반대·미확인·확정·통과·미충족·펼치기)를 서비스 그림으로 그린다.
 * 기호 글자(♥ 🚫 ✓ ★ ▾)는 OS·글꼴마다 모양이 다르고 일부 기기는 이모지로 그려서 쓰지 않는다(DESIGN.md Don't, #1340).
 *
 * 결은 핑고와 지도 핀을 따른다: 면은 통통하게 채우고, 선은 굵기 2.4에 끝과 꺾임을 둥글게 한다. 16×16 한 판에 그리고
 * 색은 currentColor 한 색이다(반대 표시의 X는 면을 오려 내서 어느 바탕 위에서도 바탕이 비친다).
 * 뜻은 옆 글자(「좋음」「반대」)나 버튼의 aria-label 이 전하므로 그림은 aria-hidden 이다.
 */
export type MarkKind = 'like' | 'against' | 'unknown' | 'star' | 'check' | 'cross' | 'chevronDown' | 'chevronUp'

/** 좋음 하트. 지도 확정 핀 머리의 하트도 이 모양을 줄여 쓴다(features/map/pinMarker). */
export const LIKE_PATH =
  'M8 14.3c-.45 0-.85-.17-1.25-.45C3.5 11.5 1.3 9.3 1.3 6.45 1.3 4.2 3 2.5 5.15 2.5c1.2 0 2.2.55 2.85 1.45.65-.9 1.65-1.45 2.85-1.45 2.15 0 3.85 1.7 3.85 3.95 0 2.85-2.2 5.05-5.45 7.4-.4.28-.8.45-1.25.45z'

const LINE = { fill: 'none', stroke: 'currentColor', strokeWidth: 2.4, strokeLinecap: 'round', strokeLinejoin: 'round' } as const

const SHAPES: Record<MarkKind, ReactNode> = {
  like: <path fill="currentColor" d={LIKE_PATH} />,
  against: (
    <path
      fill="currentColor"
      fillRule="evenodd"
      d="M1.4 8a6.6 6.6 0 1 0 13.2 0A6.6 6.6 0 1 0 1.4 8zM8 6.44l2.17-2.17a1.1 1.1 0 0 1 1.56 1.56L9.56 8l2.17 2.17a1.1 1.1 0 0 1-1.56 1.56L8 9.56l-2.17 2.17a1.1 1.1 0 0 1-1.56-1.56L6.44 8 4.27 5.83a1.1 1.1 0 0 1 1.56-1.56z"
    />
  ),
  unknown: (
    <>
      <path {...LINE} d="M5.6 5.9c0-1.45 1.05-2.45 2.45-2.45 1.4 0 2.4.95 2.4 2.2 0 1.65-2.45 1.85-2.45 3.75" />
      <circle cx="8" cy="12.6" r="1.35" fill="currentColor" />
    </>
  ),
  star: (
    <path
      fill="currentColor"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinejoin="round"
      d="M8 2.4L9.7 6.25 13.9 6.68 10.76 9.5 11.64 13.62 8 11.5 4.36 13.62 5.24 9.5 2.1 6.68 6.3 6.25Z"
    />
  ),
  check: <path {...LINE} d="M3.4 8.6l3 2.9 6.2-6.7" />,
  cross: <path {...LINE} d="M4.6 4.6l6.8 6.8M11.4 4.6l-6.8 6.8" />,
  chevronDown: <path {...LINE} d="M4.2 6.4L8 10.2l3.8-3.8" />,
  chevronUp: <path {...LINE} d="M4.2 9.6L8 5.8l3.8 3.8" />,
}

export default function Mark({ kind, size = 14 }: { kind: MarkKind; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true" className="inline-block shrink-0 align-[-0.125em]">
      {SHAPES[kind]}
    </svg>
  )
}
