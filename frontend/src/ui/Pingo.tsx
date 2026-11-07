import { useId, type ReactNode } from 'react'

import { PINGO_MARK } from './pingoMark'

/**
 * 핑고 — 서비스의 안내자(DESIGN.md 「핑고」). 평면 2D 기본형 SVG다. 시트·패널 안에서는 3D 렌더가 겉돌아서 평면만 쓴다(2026-10-19).
 *
 * 표정은 캐릭터 가이드 v2(2026-11-04, 감정 12종)를 옮겼다. 몸 모양은 같고 표정·팔·꾸밈만 다르다.
 * 삐짐·버럭·졸림은 SNS 상황극용이라 앱에는 넣지 않았다.
 * - default 기본·안내 · welcome 반가움(맞이·정리를 마침) · excited 신남(무언가 해냄)
 * - heart 설렘(AI 장소 추천 결과) · curious 궁금(조건 확인) · thinking 집중(AI가 찾는 중, 들썩인다)
 * - proud 자신만만(AI 동선 완성) · sad 아쉬움(찾던 게 없음) · flustered 당황(실패·다시 시도) · relieved 안도(고르고 끝냄)
 * - alert 의견 부족·주의 — 궁금한 얼굴에 모자·핀·물음표가 분홍(시안 ALERT)
 * - walk 응답을 기다리는 로딩(WALK CYCLE, PingoLoading)
 * - fly 로그인 화면의 첫인상 — 망토를 두르고 지도 위를 날아간다(시안에 없는 자세라 기본형을 기울여 만들었다)
 * - space 우주복을 입고 둥둥 떠다닌다 — 로그인 상태를 확인하는 동안(배포 중이면 30초까지 걸린다). 머리를 감싼 유리 헬멧 + 목 링 + 가슴 조작판, 주변에 별
 * - hug 고른 AI 후보 핀을 위에서 끌어안는다(지도, 시안에 없는 자세). 팔은 그리지 않는다 — 원을 감싼 손은 핀이 앞에서 그린다(pinMarker)
 */
export type PingoMood =
  | 'default'
  | 'welcome'
  | 'excited'
  | 'heart'
  | 'curious'
  | 'thinking'
  | 'proud'
  | 'sad'
  | 'flustered'
  | 'relieved'
  | 'alert'
  | 'walk'
  | 'fly'
  | 'hug'
  | 'space'

const BODY = 'M32 16C43 16 49 23.5 49.5 33C50 38 51.5 42 51 46C50 53 42 57 32 57C22 57 14 53 13 46C12.5 42 14 38 14.5 33C15 23.5 21 16 32 16Z'
const LINE = { stroke: 'var(--pingo-outline)', strokeWidth: 1.3 }
const INK = 'var(--ink-900)'
const STROKE = { strokeLinecap: 'round', strokeLinejoin: 'round', fill: 'none' } as const

/** 팔·발 하나 = [cx, cy, rx, ry, 기울기]. */
type Limb = [number, number, number, number, number]
const FEET: [Limb, Limb] = [[24, 55.5, 5.5, 4, 0], [40, 55.5, 5.5, 4, 0]]
const ARMS_DOWN: Limb[] = [[13.5, 43, 3.6, 7.5, 15], [50.5, 43, 3.6, 7.5, -15]]

/** 꾸밈 도형(가이드 v2 SVG 그대로). 원점 기준이라 translate·scale 로 놓는다. */
const SPARK = 'M0-5Q1-1 5 0Q1 1 0 5Q-1 1-5 0Q-1-1 0-5Z'
const DROP = 'M0-5C-1.4-2.5-3 0-3 2A3 3 0 0 0 3 2C3 0 1.4-2.5 0-5Z'
const HEART = 'M0 2C-5-2-6-6-3-7C-1-8 0-6 0-5C1-7 4-8 5-5C7-2 3 1 0 2Z'

const line = (d: string, width: number, color = INK) => <path d={d} stroke={color} strokeWidth={width} {...STROKE} />
const eyes = (l: [number, number], r: [number, number], rx: number, ry: number) => (
  <>
    <ellipse cx={l[0]} cy={l[1]} rx={rx} ry={ry} fill={INK} />
    <ellipse cx={r[0]} cy={r[1]} rx={rx} ry={ry} fill={INK} />
  </>
)
const at = (x: number, y: number, s: number, d: string, fill: string, stroke?: string) => (
  <path d={d} transform={`translate(${x} ${y}) scale(${s})`} fill={fill} stroke={stroke} strokeWidth={stroke ? 0.6 : undefined} />
)

const DOT_EYES = eyes([27, 36], [37, 36], 2, 2.9)

/** 우주복 핑고 주변에 반짝이는 별. [cx, cy, 크기, 반짝임 지연 ms] */
const STARS: [number, number, number, number][] = [[6, 10, 3, 0], [58, 16, 2.4, -700], [56, 56, 2, -1400]]
const star = (cx: number, cy: number, s: number) =>
  `M${cx} ${cy - s}Q${cx} ${cy} ${cx + s} ${cy}Q${cx} ${cy} ${cx} ${cy + s}Q${cx} ${cy} ${cx - s} ${cy}Q${cx} ${cy} ${cx} ${cy - s}Z`

/**
 * 표정 하나. `back` 은 몸 뒤, `front` 는 얼굴 앞(모은 손·턱 괸 손)에 그린다.
 * `tilt` 는 발까지 몸 전체를 움직이고, `extra` 는 몸 밖 꾸밈(반짝임·물음표)이라 기울이지 않는다.
 * `accent` 는 꾸밈 색이다 — 보통 핑고 파랑이고 alert 만 분홍이다.
 */
type Pose = { back: Limb[]; front?: Limb[]; feet?: [Limb, Limb]; tilt?: string; face: ReactNode; extra?: (accent: string) => ReactNode }

const CURIOUS: Pose = {
  tilt: 'rotate(11 32 44)',
  back: [[13.5, 43, 3.6, 7.5, 15], [51, 37, 3.6, 7.5, -30]],
  face: (
    <>
      {eyes([28, 36], [39, 36], 2, 2.9)}
      {line('M24 29Q27 26 30 29M35 31L41 31', 1.2)}
    </>
  ),
  extra: (a) => (
    <>
      {line('M56 13Q55 8 59 8Q64 8 62 12L59 15L59 17', 1.8, a)}
      <circle cx="59" cy="21" r="1" fill={a} />
    </>
  ),
}

const POSES: Record<PingoMood, Pose> = {
  default: { back: ARMS_DOWN, face: DOT_EYES },
  welcome: {
    back: [[13.5, 43, 3.6, 7.5, 15], [52, 26, 3.6, 7.5, 21]],
    face: line('M24 36Q27 31 30 36M34 36Q37 31 40 36', 1.9),
    extra: (a) => line('M56 15L58 12M59 21L63 20', 1.5, a),
  },
  excited: {
    tilt: 'translate(0 -3)',
    feet: [[23, 57, 4.3, 5.2, 22], [41, 57, 4.3, 5.2, -22]],
    back: [[12, 29, 3.6, 7.5, -38], [52, 29, 3.6, 7.5, 38]],
    face: line('M23 36Q27 29 31 36M33 36Q37 29 41 36', 2),
    extra: (a) => (
      <>
        {at(6, 14, 0.8, SPARK, a)}
        {at(61, 10, 0.6, SPARK, a)}
        {line('M7 49L4 53M57 48L61 52', 1.5, a)}
      </>
    ),
  },
  heart: {
    back: [],
    front: [[27.5, 46, 3.4, 5.3, -33], [36.5, 46, 3.4, 5.3, 33]],
    face: (
      <>
        {eyes([26, 35], [38, 35], 3, 4.2)}
        <circle cx="25.1" cy="33.5" r="0.9" fill="white" />
        <circle cx="37.1" cy="33.5" r="0.9" fill="white" />
        <ellipse cx="21" cy="41" rx="2.8" ry="1.3" fill="var(--pingo-blush)" />
        <ellipse cx="43" cy="41" rx="2.8" ry="1.3" fill="var(--pingo-blush)" />
      </>
    ),
    extra: () => (
      <>
        {at(5, 26, 0.75, HEART, 'var(--pingo-blush)')}
        {at(60, 20, 0.6, HEART, 'var(--pingo-blush)')}
      </>
    ),
  },
  curious: CURIOUS,
  alert: CURIOUS,
  thinking: {
    back: [[14, 44, 3.6, 7.5, 25]],
    front: [[39, 44, 3.7, 6.5, 58]],
    face: (
      <>
        {line('M24 36L30 36M35 36L41 36', 1.8)}
        {line('M24 30L30 31M35 31L41 29', 1.2)}
      </>
    ),
    extra: (a) => (
      <>
        <circle cx="52" cy="18" r="1.1" fill={a} />
        <circle cx="57" cy="14" r="1.5" fill={a} />
        <circle cx="63" cy="12" r="2" fill={a} />
      </>
    ),
  },
  proud: {
    tilt: 'rotate(-5 32 45)',
    back: [[14, 44, 3.6, 7.5, -34], [50, 44, 3.6, 7.5, 34]],
    face: (
      <>
        {line('M23 35Q27 39 31 35M34 35Q38 39 42 35', 1.8)}
        {line('M24 29L30 30M35 28L41 26', 1.2)}
      </>
    ),
    extra: (a) => (
      <>
        {at(6, 22, 0.75, SPARK, a)}
        {at(60, 31, 0.6, SPARK, a)}
      </>
    ),
  },
  sad: {
    tilt: 'translate(32 57) scale(1.08 .86) translate(-32 -57)',
    back: [[12.5, 47, 3.6, 7.5, 6], [51.5, 47, 3.6, 7.5, -6]],
    face: (
      <>
        {eyes([27, 38], [37, 38], 2, 2.6)}
        {line('M23 31Q27 31 30 28M34 28Q38 31 41 31', 1.2)}
        {at(41, 44, 0.7, DROP, 'var(--brand-200)', 'var(--pingo-body)')}
      </>
    ),
    extra: () => line('M15 16L15 21M20 14L20 18', 1.1, 'var(--brand-200)'),
  },
  flustered: {
    tilt: 'rotate(-6 32 46)',
    back: [[13, 30, 3.6, 7.5, -23], [53, 30, 3.6, 7.5, 23]],
    face: (
      <>
        {eyes([27, 37], [38, 37], 2.5, 3.7)}
        {line('M23 29L29 28M35 28L41 29', 1.2)}
      </>
    ),
    extra: (a) => (
      <>
        {at(48, 22, 0.95, DROP, 'var(--brand-200)', a)}
        {line('M59 17L61 13M60 25L65 25', 1.3, a)}
      </>
    ),
  },
  relieved: {
    back: [[50, 44, 3.6, 7.5, -15]],
    front: [[26, 46, 3.6, 6.5, 60]],
    face: (
      <>
        {line('M23 36Q27 40 31 36M34 36Q38 40 42 36', 1.7)}
        {line('M24 30Q27 29 30 30M35 30Q38 29 41 30', 1.2)}
      </>
    ),
    extra: () => line('M55 26Q64 28 58 32', 1.3, 'var(--brand-200)'),
  },
  walk: { back: [[13.5, 42, 3.6, 7.5, 30], [50.5, 42, 3.6, 7.5, -30]], face: DOT_EYES },
  // 앞팔은 주먹을 앞으로 뻗고(슈퍼맨), 뒷팔은 몸에 붙여 뒤로 넘긴다.
  fly: { back: [[14, 45, 3.4, 7.5, 25]], front: [[52, 21, 3.4, 8, 25]], face: DOT_EYES },
  hug: { back: [], face: line('M24.6 37Q27 33.6 29.4 37M34.6 37Q37 33.6 39.4 37', 1.8) },
  // 무중력이라 두 팔이 힘없이 위로 뜬다. 별은 몸과 같이 떠다니지 않는다.
  space: {
    back: [[12.5, 37, 3.4, 7.5, 55], [51.5, 37, 3.4, 7.5, -55]],
    face: DOT_EYES,
    extra: () =>
      STARS.map(([cx, cy, s, delay]) => (
        <path key={cx} d={star(cx, cy, s)} fill="var(--brand-300)" className="motion-safe:animate-pingo-twinkle" style={{ animationDelay: `${delay}ms` }} />
      )),
  },
}

/** 날 때만 몸을 앞으로 기울이고 망토·바람 줄이 붙어서 그림 틀을 넓힌다. */
const FLY_BOX = { x: -26, y: 0, w: 100, h: 70 }
const CAPE = 'M47 30C47 48 30 61 4 66Q1 61-6 63Q-5 57-13 57Q-9 51-16 47C-4 45 8 39 17 30Z'

export default function Pingo({ size = 40, mood = 'default', peek = false }: { size?: number; mood?: PingoMood; peek?: boolean }) {
  const clip = useId()
  // 시안 「BOTTOM NAVIGATION」: 상자 윗변에 손을 걸치고 고개만 내민다. 눈 아래에서 자른다.
  const fly = mood === 'fly'
  const h = peek ? 44 : 64
  const cap = mood === 'alert' ? 'var(--pingo-alert)' : 'var(--pingo-body)'
  const pose = POSES[mood]
  const limb = ([cx, cy, rx, ry, r]: Limb, className?: string) => (
    <ellipse key={`${cx}-${cy}`} cx={cx} cy={cy} rx={rx} ry={ry} transform={r ? `rotate(${r} ${cx} ${cy})` : undefined} fill="white" {...LINE} className={className} />
  )
  // 움직임은 상태를 알릴 때만(DESIGN.md Motion 「핑고 예외」) — 찾는 중엔 제자리에서 들썩이고, 로딩엔 뒤뚱뒤뚱 걷는다.
  // 로그인 화면에서 날 때도 들썩인다. 움직임 줄이기 설정이면 멈춘다.
  const motion = mood === 'thinking' || fly ? 'motion-safe:animate-pingo-bob' : ''
  const walk = mood === 'walk'
  const space = mood === 'space'
  const [leftFoot, rightFoot] = pose.feet ?? FEET

  return (
    <svg
      width={fly ? (size * FLY_BOX.w) / 64 : size}
      height={fly ? (size * FLY_BOX.h) / 64 : (size * h) / 64}
      viewBox={fly ? `${FLY_BOX.x} ${FLY_BOX.y} ${FLY_BOX.w} ${FLY_BOX.h}` : `0 0 64 ${h}`}
      // 반짝임·물음표 같은 꾸밈은 그림 틀 밖으로 조금 나간다. 틀은 몸 크기로 두어 놓인 자리를 바꾸지 않는다.
      overflow={peek ? undefined : 'visible'}
      aria-hidden="true"
      className={`shrink-0 ${motion}`}
    >
      {fly && <path d="M-24 18H-10M-25 30H-14M-22 42H-12" stroke="var(--brand-300)" strokeWidth="2" strokeLinecap="round" />}
      {/* 우주복은 천천히 오르내리며 좌우로 기운다(가운데를 축으로). */}
      <g
        transform={fly ? 'rotate(40 32 36)' : pose.tilt}
        className={space ? 'motion-safe:animate-pingo-drift' : undefined}
        style={space ? { transformOrigin: '32px 36px' } : undefined}
      >
        {fly && <path d={CAPE} fill="var(--brand-600)" className="motion-safe:animate-pingo-flutter" style={{ transformOrigin: '24px 34px' }} />}
        {/* 걸을 땐 두 발을 번갈아 든다(반 박자 차이). 든 발은 몸 뒤로 숨는다. */}
        {!peek && limb(leftFoot, walk ? 'motion-safe:animate-pingo-step' : undefined)}
        {!peek && limb(rightFoot, walk ? 'motion-safe:animate-pingo-step [animation-delay:-300ms]' : undefined)}
        {/* 발을 뺀 나머지는 발밑을 축으로 좌우로 기우뚱한다. */}
        <g className={walk ? 'motion-safe:animate-pingo-waddle' : undefined} style={walk ? { transformOrigin: '32px 58px' } : undefined}>
          {!peek && pose.back.map((l) => limb(l))}
          <clipPath id={clip}>
            <path d={BODY} />
          </clipPath>
          <path d={BODY} fill="white" />
          <path d="M0 0H64V26.5C48 29.5 16 29.5 0 26.5Z" fill={cap} clipPath={`url(#${clip})`} />
          <path d={BODY} fill="none" {...LINE} />
          {/* 머리 위 지도 핀 */}
          <path d="M32 16C28.5 12.8 27 10.6 27 8.5A5 5 0 0 1 37 8.5C37 10.6 35.5 12.8 32 16Z" fill={cap} />
          <circle cx="32" cy="8.5" r="1.9" fill="white" />
          {pose.face}
          {/* 우주복: 머리를 감싼 유리 헬멧(머리 핀은 안테나처럼 밖으로) + 목 링 + 가슴 조작판. 왼쪽 위 흰 줄은 유리에 비친 빛 */}
          {space && (
            <>
              <circle cx="32" cy="31" r="20" fill="var(--brand-300)" fillOpacity="0.18" {...LINE} />
              <path d="M17.5 27Q19 19.5 25.5 15.5" stroke="white" strokeWidth="2" strokeLinecap="round" fill="none" />
              <path d="M17 45.5Q32 53 47 45.5" stroke="var(--brand-300)" strokeWidth="3" strokeLinecap="round" fill="none" />
              <rect x="27" y="50" width="10" height="4.5" rx="1.5" fill="var(--brand-300)" />
              <circle cx="30" cy="52.25" r="0.9" fill="white" />
              <circle cx="34" cy="52.25" r="0.9" fill="white" />
            </>
          )}
          {peek ? (
            <>
              <ellipse cx="16" cy="41" rx="6.5" ry="3.2" fill="white" {...LINE} />
              <ellipse cx="48" cy="41" rx="6.5" ry="3.2" fill="white" {...LINE} />
            </>
          ) : (
            pose.front?.map((l) => limb(l))
          )}
        </g>
      </g>
      {!peek && pose.extra?.(cap)}
    </svg>
  )
}

/**
 * 단순화 로고(시안 「Simplified Version」) — 얼굴만. 작은 아이콘 자리(하단 탭, 넓은 화면 탭 줄)에 쓴다.
 */
export function PingoMark({ size = 28 }: { size?: number }) {
  const face = 'var(--pingo-body)'
  const hole = 'white'
  const { pin, hole: h, face: f, eyes } = PINGO_MARK
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className="shrink-0">
      <path d={pin} fill={face} />
      <circle cx={h.cx} cy={h.cy} r={h.r} fill={hole} />
      <rect x={f.x} y={f.y} width={f.w} height={f.h} rx={f.rx} fill={face} />
      {eyes.map((e) => (
        <ellipse key={e.cx} cx={e.cx} cy={e.cy} rx={e.rx} ry={e.ry} fill="var(--ink-900)" />
      ))}
    </svg>
  )
}
