import { pinGlyph, type PinGlyph } from './pinGlyph'

/** 지도 핀 하나를 (x, y)에 — 지도와 같은 그림(`pinGlyph`, 상수로만 만든 마크업). */
function Pin({ x, y, glyph }: { x: number; y: number; glyph: PinGlyph }) {
  return <g transform={`translate(${x} ${y})`} dangerouslySetInnerHTML={{ __html: pinGlyph(glyph) }} />
}

/** 로그인·초대 화면의 작은 지도 그림(Figma 1·2절). 실제 지도가 아니라 장식이라 스크린 리더에서 숨긴다. */
export default function MapIllustration({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 320 140" className={`w-full ${className}`} aria-hidden="true">
      <rect width="320" height="140" rx="12" fill="var(--ink-100)" />
      <path d="M0 98 L320 52 L320 66 L0 112 Z" fill="#fff" />
      <rect x="196" y="0" width="12" height="140" fill="#fff" />
      {/* 의견이 다 모인 일반 핀 · 올리기 전 AI 후보(핑고 핀) · 참여율 절반. */}
      <Pin x={70} y={30} glyph={{ kind: 'normal', ratio: 1 }} />
      <Pin x={112} y={52} glyph={{ kind: 'candidate' }} />
      <Pin x={250} y={40} glyph={{ kind: 'normal', ratio: 0.5 }} />
    </svg>
  )
}
