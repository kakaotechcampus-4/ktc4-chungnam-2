import type { ReactNode } from 'react'

import { pinGlyph } from './pinGlyph'

/**
 * 지도 대표 이미지의 기본 그림(#1445) — 지도 지역의 명소를 핑고와 같은 결(평면 2D, 채운 면, 둥근 끝)로 그린다.
 * 핑고 캐릭터는 넣지 않는다(핑고는 AI가 말할 때만 나온다, DESIGN.md). 사용자가 이미지를 올리면 그 이미지가 대신 보인다.
 * 바탕은 지도 색(파스텔)이고, 고르지 않았으면 ink-100 이다. 명소는 흰 면 + 진한 잉크 몇 색이라 어느 바탕에서도 보인다.
 * 320×140 한 판에 그리고 카드 폭에 맞춰 늘린다(가운데 기준으로 잘림). 장식이라 스크린 리더에서 숨긴다.
 */
const INK = 'var(--ink-700)'
const DARK = 'var(--ink-900)'
const WATER = 'var(--brand-200)'
const ROOF_RED = '#B5483A'
const HILL = '#A9C7A8'

/** 하늘과 땅 — 모든 그림의 공통 배경. */
function Backdrop() {
  return (
    <>
      <circle cx="270" cy="32" r="14" fill="#fff" opacity="0.7" />
      <rect x="34" y="26" width="38" height="10" rx="5" fill="#fff" opacity="0.8" />
      <rect x="52" y="18" width="24" height="10" rx="5" fill="#fff" opacity="0.8" />
      <rect x="0" y="118" width="320" height="22" fill="#fff" opacity="0.55" />
    </>
  )
}

/** 서울 — 광화문. 돌 기단의 홍예문 셋, 붉은 누각 두 층, 처마 끝이 들린 지붕. */
const Seoul = (
  <>
    <rect x="96" y="84" width="128" height="36" rx="3" fill="var(--ink-200)" />
    <path d="M150 120V104a10 10 0 0 1 20 0v16z" fill="var(--ink-600)" />
    <path d="M117 120v-13a8 8 0 0 1 16 0v13zM187 120v-13a8 8 0 0 1 16 0v13z" fill="var(--ink-600)" />
    <rect x="112" y="66" width="96" height="18" fill={ROOF_RED} />
    <path d="M124 70v12M140 70v12M156 70v12M172 70v12M188 70v12" stroke="#fff" strokeWidth="2" strokeLinecap="round" opacity="0.6" />
    <path d="M94 70q14-3 28-12h76q14 9 28 12q-14-2-28-2H122q-14 0-28 2z" fill={INK} />
    <rect x="128" y="44" width="64" height="14" fill={ROOF_RED} />
    <path d="M108 47q14-4 26-16h52q12 12 26 16q-13-2-26-2h-52q-13 0-26 2z" fill={INK} />
    <rect x="136" y="27" width="48" height="5" rx="2.5" fill={DARK} />
  </>
)

/** 부산 — 광안대교. 바다 위 두 주탑과 늘어진 주케이블. */
const BRIDGE_HANGERS = [120, 130, 140, 150, 160, 170, 180, 190, 200].map((x) => {
  const t = (x - 110) / 100
  return { x, y: 32 + 176 * t * (1 - t) }
})
const Busan = (
  <>
    <rect x="0" y="96" width="320" height="44" fill={WATER} />
    <path d="M24 114h22M86 124h28M210 112h26M262 126h24" stroke="#fff" strokeWidth="3" strokeLinecap="round" opacity="0.8" />
    <path d="M10 88Q70 80 110 32Q160 120 210 32Q250 80 310 88" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" />
    {BRIDGE_HANGERS.map(({ x, y }) => (
      <path key={x} d={`M${x} ${y.toFixed(1)}V88`} stroke="#fff" strokeWidth="1.5" opacity="0.85" />
    ))}
    <rect x="106" y="28" width="8" height="74" rx="2" fill="#fff" />
    <rect x="206" y="28" width="8" height="74" rx="2" fill="#fff" />
    <rect x="103" y="50" width="14" height="4" rx="2" fill={INK} />
    <rect x="203" y="50" width="14" height="4" rx="2" fill={INK} />
    <rect x="0" y="86" width="320" height="7" fill="#fff" />
    <rect x="0" y="93" width="320" height="3" fill={INK} opacity="0.5" />
  </>
)

/** 대구 — 83타워. 언덕 위 가는 기둥, 전망층, 안테나. */
const Daegu = (
  <>
    <path d="M0 118q60-34 130-18t190 6v34H0z" fill={HILL} />
    <path d="M154 112l3-58h6l3 58z" fill="#fff" />
    <path d="M148 54q12-16 24 0z" fill="#fff" />
    <rect x="146" y="54" width="28" height="9" rx="3" fill={INK} />
    <rect x="150" y="63" width="20" height="4" rx="2" fill="#fff" />
    <rect x="159" y="14" width="2" height="28" rx="1" fill={INK} />
    <circle cx="160" cy="14" r="2.5" fill={INK} />
    <rect x="148" y="108" width="24" height="10" rx="2" fill="#fff" />
    <circle cx="96" cy="104" r="9" fill="#fff" opacity="0.6" />
    <circle cx="226" cy="106" r="11" fill="#fff" opacity="0.6" />
  </>
)

/** 광주 — 무등산 서석대. 둥근 산마루와 꼭대기의 세로 돌기둥. */
const SEOSEOK = [126, 132, 138, 144, 150, 156].map((x, i) => ({ x, h: [16, 24, 30, 28, 22, 14][i] }))
const Gwangju = (
  <>
    <path d="M190 120q40-46 70-46t60 30v16z" fill={HILL} opacity="0.7" />
    <path d="M30 120Q96 52 142 50T262 120z" fill={HILL} />
    {SEOSEOK.map(({ x, h }) => (
      <rect key={x} x={x} y={56 - h / 2} width="5" height={h} rx="1.5" fill={INK} opacity="0.55" />
    ))}
  </>
)

/** 대전 — 엑스포 한빛탑. 위로 가늘어지는 탑과 가운데의 둥근 전망구. */
const Daejeon = (
  <>
    <rect x="118" y="106" width="84" height="12" rx="3" fill="#fff" />
    <path d="M160 10l12 96h-24z" fill="#fff" />
    <path d="M160 10l12 96h-12z" fill={INK} opacity="0.15" />
    <circle cx="160" cy="62" r="13" fill="var(--brand-300)" />
    <ellipse cx="160" cy="62" rx="20" ry="4" fill="none" stroke={INK} strokeWidth="2.4" />
    <rect x="132" y="112" width="8" height="6" rx="1" fill={INK} opacity="0.4" />
    <rect x="180" y="112" width="8" height="6" rx="1" fill={INK} opacity="0.4" />
  </>
)

/** 춘천 — 소양강 스카이워크. 강 위로 뻗은 유리 다리와 끝의 둥근 전망대, 뒤로 산. */
const Chuncheon = (
  <>
    <path d="M0 96q50-40 100-26t90-10 130 20v16H0z" fill={HILL} opacity="0.75" />
    <rect x="0" y="94" width="320" height="46" fill={WATER} />
    <path d="M232 112h30M256 124h34M40 128h22" stroke="#fff" strokeWidth="3" strokeLinecap="round" opacity="0.8" />
    <rect x="0" y="82" width="196" height="6" fill="#fff" />
    <rect x="0" y="88" width="196" height="3" fill="var(--brand-300)" />
    <ellipse cx="206" cy="85" rx="20" ry="6" fill="#fff" />
    <path d="M0 76h196" stroke={INK} strokeWidth="2" opacity="0.5" />
    <path d="M30 76v6M70 76v6M110 76v6M150 76v6M190 76v6" stroke={INK} strokeWidth="1.5" opacity="0.5" />
    <rect x="58" y="91" width="4" height="24" fill="#fff" opacity="0.8" />
    <rect x="128" y="91" width="4" height="24" fill="#fff" opacity="0.8" />
  </>
)

/** 지역을 고르지 않았거나 그림이 없는 지역 — 길 위의 핀 둘. */
const Fallback = (
  <>
    <path d="M0 112L320 78v14L0 126z" fill="#fff" />
    {/* 지도와 같은 핀 그림(`pinGlyph`, 상수로만 만든 마크업) — 일반 · 확정. */}
    <g transform="translate(110 46)" dangerouslySetInnerHTML={{ __html: pinGlyph({ kind: 'normal', ratio: 1 }) }} />
    <g transform="translate(196 34)" dangerouslySetInnerHTML={{ __html: pinGlyph({ kind: 'confirmed' }) }} />
  </>
)

/** 시·도 라벨(features/maps/regions) → 그림. 열린 지역(AVAILABLE_REGIONS)마다 하나씩이다. */
const BY_REGION: Record<string, ReactNode> = {
  서울특별시: Seoul,
  부산광역시: Busan,
  대구광역시: Daegu,
  광주광역시: Gwangju,
  대전광역시: Daejeon,
  강원특별자치도: Chuncheon,
}

export function hasRegionCover(region?: string) {
  return region != null && region in BY_REGION
}

/** 하늘은 늘 ink-100 이다 — 지도 색은 카드 바탕에만 쓴다(#1537). */
export default function RegionCover({ region, className = '' }: { region?: string; className?: string }) {
  return (
    <svg viewBox="0 0 320 140" preserveAspectRatio="xMidYMid slice" className={className} aria-hidden="true">
      <rect width="320" height="140" fill="var(--ink-100)" />
      <Backdrop />
      {(region && BY_REGION[region]) ?? Fallback}
    </svg>
  )
}
