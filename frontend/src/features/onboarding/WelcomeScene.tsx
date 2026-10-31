import type { CSSProperties, ReactNode } from 'react'
import { Search } from 'lucide-react'

import AgainstMark from '@/ui/AgainstMark'
import Pingo, { type PingoMood } from '@/ui/Pingo'

import { usePhaseLoop } from './usePhaseLoop'

export type SceneKind = 'pin' | 'reaction' | 'ai' | 'shortlist'

/**
 * 첫 로그인 온보딩의 장면 — 연한 지도 판 위에서 핑고가 그 장의 기능을 직접 쓰는 모습을 되풀이한다(DESIGN.md Motion 「핑고 예외」).
 * 장면은 몇 단계를 정해진 시간마다 돈다. 새로 나타나는 것만 등장 클래스로 한 번 나오고, 옮겨 가는 것은 transition 이다.
 * 움직임 줄이기면 마지막 단계에서 멈춘다. 뜻은 옆 제목·설명 글이 전하므로 장면은 스크린 리더에서 숨긴다.
 * 자리는 판에 대한 % 라서 판이 커지면(넓은 화면) 같이 커진다. 판은 4:3 이다.
 */
export default function WelcomeScene({ kind }: { kind: SceneKind }) {
  const Scene = SCENES[kind]
  return (
    <div aria-hidden="true" className="relative aspect-[4/3] w-full select-none overflow-hidden rounded-2xl bg-ink-100">
      {/* 지도 그림의 길(MapIllustration 과 같은 결). */}
      <svg viewBox="0 0 320 240" className="absolute inset-0 size-full">
        <path d="M0 176L320 112V130L0 194Z" fill="#fff" />
        <rect x="226" width="14" height="240" fill="#fff" />
      </svg>
      <Scene />
    </div>
  )
}

const SCENES: Record<SceneKind, () => ReactNode> = { pin: PinScene, reaction: ReactionScene, ai: AiScene, shortlist: ShortlistScene }

/** 판 위 한 점(% 좌표)에 놓는다. `anchor` 는 그 점에 올 자기 자리 — 핀은 끝(아래 가운데)이다. */
function At({ x, y, anchor = 'bottom', className = '', style, children }: {
  x: number
  y: number
  anchor?: 'bottom' | 'center' | 'top-left'
  className?: string
  style?: CSSProperties
  children: ReactNode
}) {
  const shift = { bottom: '-50%, -100%', center: '-50%, -50%', 'top-left': '0, 0' }[anchor]
  return (
    <div className={`absolute ${className}`} style={{ left: `${x}%`, top: `${y}%`, transform: `translate(${shift})`, ...style }}>
      {children}
    </div>
  )
}

/** 핑고를 판 폭의 `w`% 로 그린다. 발밑 가운데가 (x, y) 다. */
function PingoAt({ x, y, w, mood }: { x: number; y: number; w: number; mood: PingoMood }) {
  return (
    <At x={x} y={y} style={{ width: `${w}%` }}>
      <div className="[&>svg]:h-auto [&>svg]:w-full">
        <Pingo size={64} mood={mood} />
      </div>
    </At>
  )
}

const PIN_PATH = 'M12 2C7.6 2 4 5.6 4 10c0 6 8 20 8 20s8-14 8-20c0-4.4-3.6-8-8-8z'

/** 지도 핀(pinMarker 와 같은 물방울). 일반은 빨강 실선, 확정은 골드 + 순서 번호. */
function ScenePin({ confirmed = false, n }: { confirmed?: boolean; n?: number }) {
  return (
    <svg viewBox="0 0 24 32" width="24" height="32" className="drop-shadow-[0_1px_2px_rgba(20,22,31,0.3)]">
      <path
        d={PIN_PATH}
        strokeLinejoin="round"
        fill={confirmed ? 'var(--pin-confirmed)' : 'var(--pin-fill-full)'}
        stroke={confirmed ? 'var(--pin-confirmed-mark)' : 'var(--pin-stroke)'}
        strokeWidth={confirmed ? 1.5 : 2.5}
      />
      {n != null ? (
        <text x="12" y="13.5" textAnchor="middle" fontSize="10" fontWeight="700" fill="var(--pin-confirmed-mark)">
          {n}
        </text>
      ) : (
        <circle cx="12" cy="10" r="3.2" fill="#fff" />
      )}
    </svg>
  )
}

/** 판 위 작은 흰 카드(검색창·의견·확정 리스트). 지도 위에 뜬 것이라 그림자를 준다. */
const CARD = 'rounded-xl bg-white shadow-float'

/** ① 검색창 → ② 「핀 찍기」 눌림 → ③ 핑고가 든 핀이 지도에 꽂힘 → ④ 흐려지며 처음으로. */
const PIN_PHASES = [800, 500, 1600, 400]
function PinScene() {
  // 마지막 단계는 핀이 흐려지는 사이라, 움직임 줄이기면 핀이 꽂힌 ③에 머문다.
  const phase = usePhaseLoop(PIN_PHASES, 2)
  // 핀 끝: 핑고가 든 손 위 → 지도 위 자리. 떨어지는 단계에서만 옮겨 가고, 처음으로 돌아갈 땐 안 보이는 채 바로 간다.
  const held = phase < 2
  return (
    <>
      <At x={6} y={7} anchor="top-left" className="right-[6%]">
        <div className={`${CARD} flex h-9 items-center gap-1.5 px-3 text-xs text-ink-700`}>
          <Search size={12} aria-hidden="true" className="text-ink-500" />
          카페
          <span
            className={`ml-auto rounded-full px-2 py-0.5 text-label font-bold text-white transition-[transform,background-color] duration-200 ease-out motion-reduce:transition-none ${
              phase === 1 ? 'scale-95 bg-brand-700' : 'bg-brand-600'
            }`}
          >
            핀 찍기
          </span>
        </div>
      </At>
      <PingoAt x={32} y={92} w={30} mood={held ? 'wave' : 'happy'} />
      {phase >= 2 && (
        <At x={66} y={80} anchor="center">
          <div key={phase === 2 ? 'drop' : 'stay'} className="enter-fade h-1.5 w-6 rounded-full bg-ink-300/70" />
        </At>
      )}
      <At
        x={held ? 41 : 66}
        y={held ? 65 : 80}
        className={`${phase === 2 ? 'transition-[left,top] duration-300 ease-out' : ''} ${
          phase === 3 ? 'opacity-0 transition-opacity duration-200' : ''
        } motion-reduce:transition-none`}
      >
        <ScenePin />
      </At>
    </>
  )
}

/** ① 핀과 의견 카드 → ② 좋음 → ③ 반대 + 이유 칩. */
const REACTION_PHASES = [800, 1200, 1800]
const REACTION_MOOD: PingoMood[] = ['default', 'happy', 'default']
function ReactionScene() {
  const phase = usePhaseLoop(REACTION_PHASES)
  const like = phase === 1
  const against = phase === 2
  return (
    <>
      <At x={30} y={46}>
        <ScenePin />
      </At>
      <At x={50} y={16} anchor="top-left" className="w-[44%]">
        <div className={`${CARD} p-2`}>
          <div className="grid grid-cols-2 gap-1.5">
            <ReactionPill on={like} tone="good">
              ♥ 좋음
            </ReactionPill>
            <ReactionPill on={against} tone="bad">
              <AgainstMark size={12} /> 반대
            </ReactionPill>
          </div>
          {against && (
            <span key="reason" className="enter-pop mt-1.5 inline-flex rounded-full border border-[var(--bad-line)] bg-[var(--bad-bg)] px-2 py-0.5 text-label font-bold text-[var(--bad-text)]">
              너무 멀어요
            </span>
          )}
        </div>
      </At>
      <PingoAt x={26} y={94} w={30} mood={REACTION_MOOD[phase]} />
    </>
  )
}

/** 핀 상세의 「내 의견」 두 칸과 같은 색(PinDetail R 표). */
function ReactionPill({ on, tone, children }: { on: boolean; tone: 'good' | 'bad'; children: ReactNode }) {
  return (
    <span
      className="flex items-center justify-center gap-0.5 rounded-lg border py-1 text-label font-bold transition-colors duration-200 ease-out motion-reduce:transition-none"
      style={
        on
          ? { background: `var(--${tone}-bg)`, borderColor: `var(--${tone}-line)`, color: `var(--${tone}-text)` }
          : { background: '#fff', borderColor: 'var(--ink-200)', color: 'var(--ink-600)' }
      }
    >
      {children}
    </span>
  )
}

/** ① 핀마다 남긴 의견들 → ② 의견이 핑고에게 모임(핑고는 찾는 중) → ③ 모두에게 맞는 후보 핀 둘이 한꺼번에 나타남. */
const AI_PHASES = [1200, 1200, 2000]
const OPINIONS: { x: number; y: number; like: boolean; text: string }[] = [
  { x: 8, y: 14, like: true, text: '조용해요' },
  { x: 34, y: 36, like: false, text: '너무 멀어요' },
  { x: 6, y: 58, like: true, text: '주차돼요' },
]
function AiScene() {
  const phase = usePhaseLoop(AI_PHASES)
  return (
    <>
      {phase < 2 &&
        OPINIONS.map(({ x, y, like, text }) => (
          // ② 에서 핑고 머리 쪽으로 모이며 흐려진다. 처음으로 돌아갈 땐 제자리에 바로 선다.
          <At
            key={text}
            x={phase === 1 ? 70 : x}
            y={phase === 1 ? 60 : y}
            anchor="top-left"
            className={phase === 1 ? 'opacity-0 transition-[left,top,opacity] duration-300 ease-out motion-reduce:transition-none' : ''}
          >
            <span
              className="inline-flex items-center gap-0.5 rounded-full border px-2 py-0.5 text-label font-bold shadow-float"
              style={
                like
                  ? { background: 'var(--good-bg)', borderColor: 'var(--good-line)', color: 'var(--good-text)' }
                  : { background: 'var(--bad-bg)', borderColor: 'var(--bad-line)', color: 'var(--bad-text)' }
              }
            >
              {like ? '♥' : <AgainstMark size={10} />} {text}
            </span>
          </At>
        ))}
      {phase === 2 &&
        [
          [24, 40],
          [46, 62],
        ].map(([x, y]) => (
          <At key={`${x}`} x={x} y={y}>
            <div className="enter-drop relative">
              <ScenePin />
              <span className="tag tag-ai absolute -right-5 -top-2">AI</span>
            </div>
          </At>
        ))}
      <PingoAt x={74} y={92} w={30} mood={phase === 2 ? 'happy' : phase === 1 ? 'thinking' : 'default'} />
    </>
  )
}

/** ① 리스트와 핀 → ② 확정 핀(번호)으로 바뀜 → ③ 핀 사이 동선이 그려짐. */
const SHORTLIST_PHASES = [800, 1200, 1800]
const STOPS: [number, number][] = [
  [14, 34],
  [36, 52],
  [20, 78],
]
function ShortlistScene() {
  const phase = usePhaseLoop(SHORTLIST_PHASES)
  const confirmed = phase >= 1
  // 핀 끝 사이를 잇는 선(판 320×240 좌표). 길이를 넉넉히 잡아 dashoffset 으로 그린다.
  const route = STOPS.map(([x, y], i) => `${i ? 'L' : 'M'}${x * 3.2} ${y * 2.4 - 4}`).join('')
  return (
    <>
      <svg viewBox="0 0 320 240" className="absolute inset-0 size-full">
        <path
          d={route}
          fill="none"
          stroke="var(--brand-600)"
          strokeWidth="4"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeDasharray="200"
          strokeDashoffset={phase === 2 ? 0 : 200}
          className={phase === 2 ? 'transition-[stroke-dashoffset] duration-300 ease-out motion-reduce:transition-none' : ''}
        />
      </svg>
      {STOPS.map(([x, y], i) => (
        <At key={i} x={x} y={y}>
          <div key={String(confirmed)} className={confirmed ? 'enter-pop' : undefined}>
            <ScenePin confirmed={confirmed} n={confirmed ? i + 1 : undefined} />
          </div>
        </At>
      ))}
      <At x={56} y={8} anchor="top-left" className="w-[38%]">
        <div className={`${CARD} space-y-1.5 p-2`}>
          <p className="text-label font-bold text-ink-900">확정 리스트</p>
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex items-center gap-1.5">
              <span
                className="flex size-4 shrink-0 items-center justify-center rounded-full text-label font-bold transition-colors duration-200 ease-out motion-reduce:transition-none"
                style={confirmed ? { background: 'var(--pin-confirmed)', color: 'var(--pin-confirmed-mark)' } : { background: 'var(--ink-100)', color: 'var(--ink-500)' }}
              >
                {i + 1}
              </span>
              <span className="h-1.5 flex-1 rounded-full bg-ink-200" />
            </div>
          ))}
        </div>
      </At>
      <PingoAt x={74} y={94} w={28} mood={confirmed ? 'happy' : 'default'} />
    </>
  )
}
