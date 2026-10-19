import { useId } from 'react'

/**
 * 핑고 — 서비스의 안내자(DESIGN.md 「핑고」). 캐릭터 시안(PINGO_캐디.pdf)의 평면 2D 기본형을 SVG로 옮겼다.
 * 시트·패널 안에서는 3D 렌더가 겉돌아서 평면만 쓴다(2026-10-19).
 *
 * 표정은 시안 「Motion & Expression」의 상황을 따른다.
 * - default 기본·안내 · wave 정리를 마침(시안 「결정했어요!」) · happy 추천 완료(JUMP)
 * - thinking AI가 결과를 찾는 중(THINKING) · walk 응답을 기다리는 로딩(WALK CYCLE, PingoLoading)
 * - sorry 결과 없음(NO SUGGESTION) · error 실패(ERROR) · alert 의견 부족·주의(「Color Variation」 ALERT, 모자만 분홍)
 * - fly 로그인 화면의 첫인상 — 망토를 두르고 지도 위를 날아간다(시안에 없는 자세라 기본형을 기울여 만들었다)
 */
export type PingoMood = 'default' | 'wave' | 'happy' | 'thinking' | 'walk' | 'sorry' | 'error' | 'alert' | 'fly'

const BODY = 'M32 16C43 16 49 23.5 49.5 33C50 38 51.5 42 51 46C50 53 42 57 32 57C22 57 14 53 13 46C12.5 42 14 38 14.5 33C15 23.5 21 16 32 16Z'
const LINE = { stroke: 'var(--pingo-outline)', strokeWidth: 1.3 }
const FACE = { stroke: 'var(--ink-900)', strokeWidth: 1.8, strokeLinecap: 'round', fill: 'none' } as const

/** 팔 하나 = [cx, cy, rx, ry, 기울기]. 몸 뒤에 그린다. thinking 의 오른팔만 몸 앞(턱 괸 손)이다. */
type Arm = [number, number, number, number, number]
const ARMS: Record<PingoMood, [Arm, Arm]> = {
  default: [[13.5, 43, 3.6, 7.5, 15], [50.5, 43, 3.6, 7.5, -15]],
  alert: [[13.5, 43, 3.6, 7.5, 15], [50.5, 43, 3.6, 7.5, -15]],
  walk: [[13.5, 42, 3.6, 7.5, 30], [50.5, 42, 3.6, 7.5, -30]],
  error: [[12, 42, 4.5, 5.5, 0], [52, 42, 4.5, 5.5, 0]],
  wave: [[13.5, 43, 3.6, 7.5, 15], [50.5, 30, 3.4, 7.5, 12]],
  happy: [[11, 39, 4.5, 5.5, 0], [53, 39, 4.5, 5.5, 0]],
  sorry: [[13.5, 30, 3.4, 7.5, -12], [49, 45, 4.5, 5, 0]],
  thinking: [[13.5, 43, 3.6, 7.5, 15], [41, 45.5, 5.5, 3.4, -15]],
  // 앞팔은 주먹을 앞으로 뻗고(슈퍼맨), 뒷팔은 몸에 붙여 뒤로 넘긴다.
  fly: [[14, 45, 3.4, 7.5, 25], [52, 21, 3.4, 8, 25]],
}

/** 날 때만 몸을 앞으로 기울이고 망토·바람 줄이 붙어서 그림 틀을 넓힌다. */
const FLY_BOX = '-26 0 96 70'
const CAPE = 'M47 30C47 48 30 61 4 66Q1 61-6 63Q-5 57-13 57Q-9 51-16 47C-4 45 8 39 17 30Z'

export default function Pingo({ size = 40, mood = 'default', peek = false }: { size?: number; mood?: PingoMood; peek?: boolean }) {
  const clip = useId()
  // 시안 「BOTTOM NAVIGATION」: 상자 윗변에 손을 걸치고 고개만 내민다. 눈 아래에서 자른다.
  const fly = mood === 'fly'
  const h = peek ? 44 : 64
  const cap = mood === 'alert' ? 'var(--pingo-alert)' : 'var(--pingo-body)'
  const [left, right] = ARMS[mood]
  const front = mood === 'thinking'
  const arm = ([cx, cy, rx, ry, r]: Arm) => (
    <ellipse cx={cx} cy={cy} rx={rx} ry={ry} transform={`rotate(${r} ${cx} ${cy})`} fill="white" {...LINE} />
  )
  // 찾는 중엔 제자리에서 들썩이고, 추천 완료엔 한 번 뛰고, 로딩엔 뒤뚱뒤뚱 걷는다. 움직임 줄이기 설정이면 멈춘다.
  const motion = mood === 'thinking' || fly ? 'motion-safe:animate-pingo-bob' : mood === 'happy' ? 'motion-safe:animate-pingo-hop' : ''
  const walk = mood === 'walk'

  return (
    <svg
      width={fly ? (size * 88) / 64 : size}
      height={fly ? (size * 68) / 64 : (size * h) / 64}
      viewBox={fly ? FLY_BOX : `0 0 64 ${h}`}
      aria-hidden="true"
      className={`shrink-0 ${motion}`}
    >
      {fly && <path d="M-24 18H-10M-25 30H-14M-22 42H-12" stroke="var(--brand-300)" strokeWidth="2" strokeLinecap="round" />}
      <g transform={fly ? 'rotate(40 32 36)' : undefined}>
      {fly && <path d={CAPE} fill="var(--brand-600)" className="motion-safe:animate-pingo-flutter" style={{ transformOrigin: '24px 34px' }} />}
      {!peek && (
        <>
          {/* 걸을 땐 두 발을 번갈아 든다(반 박자 차이). 든 발은 몸 뒤로 숨는다. */}
          <ellipse cx="24" cy="55.5" rx="5.5" ry="4" fill="white" {...LINE} className={walk ? 'motion-safe:animate-pingo-step' : undefined} />
          <ellipse cx="40" cy="55.5" rx="5.5" ry="4" fill="white" {...LINE} className={walk ? 'motion-safe:animate-pingo-step [animation-delay:-300ms]' : undefined} />
        </>
      )}
      {/* 발을 뺀 나머지는 발밑을 축으로 좌우로 기우뚱한다. */}
      <g className={walk ? 'motion-safe:animate-pingo-waddle' : undefined} style={walk ? { transformOrigin: '32px 58px' } : undefined}>
        {!peek && arm(left)}
        {!peek && !front && arm(right)}
        <clipPath id={clip}>
          <path d={BODY} />
        </clipPath>
        <path d={BODY} fill="white" />
        <path d="M0 0H64V26.5C48 29.5 16 29.5 0 26.5Z" fill={cap} clipPath={`url(#${clip})`} />
        <path d={BODY} fill="none" {...LINE} />
        {/* 머리 위 지도 핀 */}
        <path d="M32 16C28.5 12.8 27 10.6 27 8.5A5 5 0 0 1 37 8.5C37 10.6 35.5 12.8 32 16Z" fill={cap} />
        <circle cx="32" cy="8.5" r="1.9" fill="white" />

        <Face mood={mood} />
        {peek ? (
          <>
            <ellipse cx="16" cy="41" rx="6.5" ry="3.2" fill="white" {...LINE} />
            <ellipse cx="48" cy="41" rx="6.5" ry="3.2" fill="white" {...LINE} />
          </>
        ) : (
          front && arm(right)
        )}
        {mood === 'sorry' && (
          <path d="M44 18.5C45.5 20.5 46.3 21.8 46.3 22.8A2.3 2.3 0 0 1 41.7 22.8C41.7 21.8 42.5 20.5 44 18.5Z" fill="white" {...LINE} />
        )}
      </g>
      </g>
    </svg>
  )
}

function Face({ mood }: { mood: PingoMood }) {
  switch (mood) {
    case 'happy':
      return <path d="M24.6 37Q27 33.6 29.4 37M34.6 37Q37 33.6 39.4 37" {...FACE} />
    case 'sorry':
      return <path d="M24.6 38Q27 34.6 29.4 38M34.6 38Q37 34.6 39.4 38M25 31.6L28.6 30.6M35.4 30.6L39 31.6" {...FACE} />
    case 'thinking':
      return <path d="M24.5 36H29.5M34.5 36H39.5" {...FACE} />
    case 'error':
      return <path d="M25 34L29 38M29 34L25 38M35 34L39 38M39 34L35 38" {...FACE} />
    default:
      return (
        <>
          <ellipse cx="27" cy="36" rx="2" ry="2.9" fill="var(--ink-900)" />
          <ellipse cx="37" cy="36" rx="2" ry="2.9" fill="var(--ink-900)" />
        </>
      )
  }
}

/**
 * 단순화 로고(시안 「Simplified Version」) — 얼굴만. 작은 아이콘 자리(하단 탭 AI 원, 넓은 화면 탭 줄)에 쓴다.
 * tone="white" 는 파랑 채움 원 위(활성 AI 탭)용이다.
 */
export function PingoMark({ size = 28, tone = 'blue' }: { size?: number; tone?: 'blue' | 'white' }) {
  const face = tone === 'white' ? 'white' : 'var(--pingo-body)'
  const hole = tone === 'white' ? 'var(--brand-600)' : 'white'
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className="shrink-0">
      <path d="M16 10.5C13.9 8.6 13 7.3 13 6A3 3 0 0 1 19 6C19 7.3 18.1 8.6 16 10.5Z" fill={face} />
      <circle cx="16" cy="6" r="1.1" fill={hole} />
      <rect x="5" y="11.5" width="22" height="17" rx="7" fill={face} />
      <ellipse cx="12.5" cy="20" rx="1.3" ry="1.9" fill="var(--ink-900)" />
      <ellipse cx="19.5" cy="20" rx="1.3" ry="1.9" fill="var(--ink-900)" />
    </svg>
  )
}
