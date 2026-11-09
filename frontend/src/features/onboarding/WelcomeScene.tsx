import type { CSSProperties, ReactNode } from 'react'
import { Lock, Search, Trash2 } from 'lucide-react'

import Mark from '@/ui/Mark'
import Coin from '@/ui/Coin'
import Pingo, { type PingoMood } from '@/ui/Pingo'
import { pinGlyph, type PinGlyph } from '@/ui/pinGlyph'

import { usePhaseLoop } from './usePhaseLoop'

export type SceneKind = 'pin' | 'reaction' | 'ai' | 'shortlist' | 'together' | 'invite' | 'safety' | 'credits' | 'login' | 'trash' | 'mapMouse' | 'mapTouch'

/**
 * 첫 로그인 온보딩과 자주 묻는 질문(#1538), 지도 쓰는 법(#1613)의 장면 — 연한 지도 판 위에서 핑고가 그 기능을 직접 쓰는 모습을 되풀이한다(DESIGN.md Motion 「핑고 예외」).
 * 장면은 몇 단계를 정해진 시간마다 돈다. 새로 나타나는 것만 등장 클래스로 한 번 나오고, 옮겨 가는 것은 transition 이다.
 * 움직임 줄이기면 마지막 단계에서 멈춘다. 뜻은 옆 제목·설명 글이 전하므로 장면은 스크린 리더에서 숨긴다.
 * 자리는 판에 대한 % 라서 판이 커지면(넓은 화면) 같이 커진다. 판은 4:3 이다.
 */
export default function WelcomeScene({ kind, className = 'w-full' }: { kind: SceneKind; className?: string }) {
  const Scene = SCENES[kind]
  return (
    <div aria-hidden="true" className={`keep-light relative aspect-[4/3] select-none overflow-hidden rounded-2xl bg-ink-100 ${className}`}>
      {/* 지도 그림의 길(MapIllustration 과 같은 결). */}
      <svg viewBox="0 0 320 240" className="absolute inset-0 size-full">
        <path d="M0 176L320 112V130L0 194Z" fill="#fff" />
        <rect x="226" width="14" height="240" fill="#fff" />
      </svg>
      <Scene />
    </div>
  )
}

const SCENES: Record<SceneKind, () => ReactNode> = {
  pin: PinScene,
  reaction: ReactionScene,
  ai: AiScene,
  shortlist: ShortlistScene,
  together: TogetherScene,
  invite: InviteScene,
  safety: SafetyScene,
  credits: CreditsScene,
  login: LoginScene,
  trash: TrashScene,
  mapMouse: () => <MapGestureScene touch={false} />,
  mapTouch: () => <MapGestureScene touch />,
}

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

/** 지도 핀 — 지도와 같은 그림(`ui/pinGlyph`). 일반은 참여 다 모인 빨강, 확정은 ♥ 대신 동선 순서 번호. */
function ScenePin({ confirmed = false, n }: { confirmed?: boolean; n?: number }) {
  return <PinSvg glyph={confirmed ? { kind: 'confirmed', order: n } : { kind: 'normal', ratio: 1 }} />
}

/** 올리기 전 AI 후보 핀(핑고 핀). */
function SceneCandidatePin() {
  return <PinSvg glyph={{ kind: 'candidate' }} />
}

function PinSvg({ glyph }: { glyph: PinGlyph }) {
  // pinGlyph 는 상수·숫자로만 만든 마크업이다(사용자 글 없음).
  return <svg viewBox="0 0 24 32" width="24" height="32" dangerouslySetInnerHTML={{ __html: pinGlyph(glyph) }} />
}

/** 판 위 작은 흰 카드(검색창·의견·확정 리스트). 지도 위에 뜬 것이라 그림자를 준다. */
const CARD = 'rounded-xl bg-surface shadow-float'

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
      <PingoAt x={32} y={92} w={30} mood={held ? 'welcome' : 'excited'} />
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
const REACTION_MOOD: PingoMood[] = ['default', 'heart', 'default']
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
              <Mark kind="like" size={12} /> 좋음
            </ReactionPill>
            <ReactionPill on={against} tone="bad">
              <Mark kind="against" size={12} /> 반대
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
      className="flex items-center justify-center gap-0.5 rounded-xl border py-1 text-label font-bold transition-colors duration-200 ease-out motion-reduce:transition-none"
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
              {like ? <Mark kind="like" size={10} /> : <Mark kind="against" size={10} />} {text}
            </span>
          </At>
        ))}
      {phase === 2 &&
        [
          [24, 40],
          [46, 62],
        ].map(([x, y]) => (
          <At key={`${x}`} x={x} y={y}>
            <div className="enter-drop">
              <SceneCandidatePin />
            </div>
          </At>
        ))}
      <PingoAt x={74} y={92} w={30} mood={phase === 2 ? 'heart' : phase === 1 ? 'thinking' : 'default'} />
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
      <PingoAt x={74} y={94} w={28} mood={confirmed ? 'relieved' : 'default'} />
    </>
  )
}

/** 구성원 동그라미(Avatar 와 같은 결 — ink-100 면 + 이니셜). 판 위라 흰 테두리로 띄운다. */
function SceneFace({ name }: { name: string }) {
  return <span className="flex size-7 items-center justify-center rounded-full border-2 border-white bg-ink-200 text-label font-bold text-ink-700">{name}</span>
}

/** 자주 묻는 질문 「어떤 서비스」 — ① 구성원 셋 → ②~④ 각자 핀을 하나씩 꽂음 → ⑤ 핀마다 좋음이 붙고 핑고가 반김. */
const TOGETHER_PHASES = [600, 600, 600, 600, 1800]
const TOGETHER_PINS: { x: number; y: number; who: string }[] = [
  { x: 22, y: 48, who: '민' },
  { x: 46, y: 70, who: '서' },
  { x: 62, y: 40, who: '도' },
]
function TogetherScene() {
  const phase = usePhaseLoop(TOGETHER_PHASES)
  return (
    <>
      <At x={6} y={7} anchor="top-left">
        <div className="flex -space-x-1.5">
          {TOGETHER_PINS.map((p) => (
            <SceneFace key={p.who} name={p.who} />
          ))}
        </div>
      </At>
      {TOGETHER_PINS.map((p, i) =>
        phase > i ? (
          <At key={p.who} x={p.x} y={p.y}>
            <div className="enter-drop relative">
              <ScenePin />
              {phase === 4 && (
                <span className="enter-pop absolute -right-3 -top-2 flex size-5 items-center justify-center rounded-full bg-surface shadow-float">
                  <Mark kind="like" size={11} />
                </span>
              )}
            </div>
          </At>
        ) : null,
      )}
      <PingoAt x={84} y={94} w={26} mood={phase === 4 ? 'heart' : 'default'} />
    </>
  )
}

/** 「친구 초대」 — ① 「초대 링크 공유하기」 → ② 눌림 → ③ 단톡방 말풍선에 링크가 가고 친구들이 들어옴. */
const INVITE_PHASES = [900, 500, 2000]
function InviteScene() {
  const phase = usePhaseLoop(INVITE_PHASES)
  return (
    <>
      <At x={6} y={8} anchor="top-left" className="right-[6%]">
        <span
          className={`flex h-8 items-center justify-center rounded-xl text-xs font-bold text-white transition-[transform,background-color] duration-200 ease-out motion-reduce:transition-none ${
            phase === 1 ? 'scale-95 bg-brand-700' : 'bg-brand-600'
          }`}
        >
          초대 링크 공유하기
        </span>
      </At>
      {phase === 2 && (
        <>
          <At x={8} y={36} anchor="top-left" className="w-[52%]">
            <div className="enter-pop rounded-xl rounded-tl-sm bg-[#FEE500] px-2.5 py-1.5 text-label font-semibold text-ink-900 shadow-float">
              우리 여행 지도 여기!
              <span className="mt-0.5 block truncate font-normal text-ink-700">pingo…/invites/…</span>
            </div>
          </At>
          <At x={8} y={66} anchor="top-left">
            <div className="flex -space-x-1.5">
              {['민', '서', '도'].map((n, i) => (
                <span key={n} className="enter-pop" style={{ animationDelay: `${300 + i * 200}ms`, animationFillMode: 'backwards' }}>
                  <SceneFace name={n} />
                </span>
              ))}
            </div>
          </At>
        </>
      )}
      <PingoAt x={80} y={94} w={28} mood={phase === 2 ? 'excited' : 'welcome'} />
    </>
  )
}

/** 「알레르기」 — ① 후보 핀과 조건 줄 → ② 「모름」 줄 아래 「가게에 직접 확인해 주세요」 안내가 붙음. */
const SAFETY_PHASES = [1000, 2200]
function SafetyScene() {
  const phase = usePhaseLoop(SAFETY_PHASES)
  return (
    <>
      <At x={18} y={52}>
        <SceneCandidatePin />
      </At>
      <At x={36} y={10} anchor="top-left" className="right-[6%]">
        <div className={`${CARD} space-y-1 p-2 text-label font-semibold`}>
          <p className="flex items-center gap-1 text-ink-900">
            <Mark kind="check" size={11} /> 조용해요
          </p>
          <p className="flex items-center gap-1 text-ink-900">
            <Mark kind="unknown" size={11} /> 견과류 알레르기
          </p>
          {phase === 1 && (
            <p key="ask" className="enter-pop rounded-lg bg-[var(--warn-bg)] px-1.5 py-1 text-[var(--warn-text)]">
              가게에 직접 확인해 주세요
            </p>
          )}
        </div>
      </At>
      <PingoAt x={24} y={96} w={26} mood={phase === 1 ? 'alert' : 'thinking'} />
    </>
  )
}

/** 「크레딧」 — ① 「추천 받기」 옆 크레딧 → ② 누르면 크레딧 하나가 버튼으로 들어감 → ③ 후기를 쓰면 크레딧이 다시 들어옴. 숫자는 적지 않는다(정책 값). */
const CREDITS_PHASES = [900, 800, 2000]
function CreditsScene() {
  const phase = usePhaseLoop(CREDITS_PHASES)
  return (
    <>
      <At x={6} y={8} anchor="top-left" className="right-[6%]">
        <div className="flex items-center gap-2">
          <span
            className={`flex h-8 flex-1 items-center justify-center rounded-xl text-xs font-bold text-white transition-[transform,background-color] duration-200 ease-out motion-reduce:transition-none ${
              phase === 1 ? 'scale-95 bg-brand-700' : 'bg-brand-600'
            }`}
          >
            추천 받기
          </span>
          <span className={`${CARD} flex h-8 items-center gap-1 px-2 text-label font-bold text-ink-700`}>
            <Coin size={14} /> 크레딧
          </span>
        </div>
      </At>
      {phase === 1 && (
        <At x={80} y={18} anchor="center">
          <span className="enter-fade block opacity-0 transition-transform duration-500 ease-in motion-reduce:transition-none" style={{ transform: 'translateX(-120px)' }}>
            <Coin size={16} />
          </span>
        </At>
      )}
      {phase === 2 && (
        <At x={8} y={40} anchor="top-left" className="w-[56%]">
          <div className={`${CARD} enter-pop p-2`}>
            <p className="text-label font-bold text-ink-900">후기 쓰기</p>
            <p className="mt-0.5 flex gap-0.5">
              {[0, 1, 2, 3, 4].map((i) => (
                <Mark key={i} kind="star" size={11} />
              ))}
            </p>
            <span className="enter-pop mt-1 inline-flex items-center gap-0.5 rounded-full bg-[var(--confirmed-bg)] px-1.5 py-0.5 text-label font-bold text-[var(--pin-confirmed-mark)]" style={{ animationDelay: '500ms', animationFillMode: 'backwards' }}>
              <Coin size={11} /> 크레딧 받음
            </span>
          </div>
        </At>
      )}
      <PingoAt x={82} y={94} w={26} mood={phase === 2 ? 'proud' : 'default'} />
    </>
  )
}

/** 「게스트」 — ① 잠긴 AI 추천과 로그인 버튼 둘(카카오·구글) → ② 하나를 누름 → ③ 잠금이 풀리고 핑고가 나옴. */
const LOGIN_PHASES = [1000, 500, 2000]
function LoginScene() {
  const phase = usePhaseLoop(LOGIN_PHASES)
  return (
    <>
      <At x={6} y={8} anchor="top-left">
        <span className={`${CARD} flex h-8 items-center gap-1 px-2.5 text-label font-bold ${phase === 2 ? 'text-link' : 'text-ink-500'}`}>
          {phase === 2 ? <span className="enter-pop">AI 추천 열림</span> : <><Lock size={12} aria-hidden="true" /> AI 추천</>}
        </span>
      </At>
      <At x={6} y={34} anchor="top-left" className="w-[56%]">
        <div className="space-y-1.5">
          <span
            className={`flex h-7 items-center justify-center rounded-lg bg-[#FEE500] text-label font-bold text-ink-900 transition-transform duration-200 motion-reduce:transition-none ${phase === 1 ? 'scale-95' : ''}`}
          >
            카카오로 시작하기
          </span>
          <span className="flex h-7 items-center justify-center rounded-lg border border-ink-200 bg-surface text-label font-bold text-ink-900">
            Google로 시작하기
          </span>
        </div>
      </At>
      <PingoAt x={80} y={94} w={28} mood={phase === 2 ? 'excited' : 'curious'} />
    </>
  )
}

/** 「지운 핀」 — ① 지도의 핀 → ② 휴지통으로 들어감 → ③ 「삭제한 핀」에서 되돌리기 → ④ 핀이 제자리로 돌아옴. */
const TRASH_PHASES = [800, 900, 900, 1500]
function TrashScene() {
  const phase = usePhaseLoop(TRASH_PHASES)
  const inTrash = phase === 1 || phase === 2
  return (
    <>
      <At x={84} y={86} anchor="center">
        <span className={`${CARD} flex size-9 items-center justify-center text-ink-600`}>
          <Trash2 size={18} aria-hidden="true" />
        </span>
      </At>
      <At
        x={inTrash ? 84 : 36}
        y={inTrash ? 82 : 56}
        className={`${phase === 1 || phase === 3 ? 'transition-[left,top,opacity] duration-500 ease-out' : ''} ${inTrash ? 'opacity-0' : ''} motion-reduce:transition-none`}
      >
        <ScenePin />
      </At>
      {phase === 2 && (
        <At x={6} y={8} anchor="top-left" className="w-[58%]">
          <div className={`${CARD} enter-pop flex items-center justify-between gap-1 px-2 py-1.5`}>
            <span className="text-label font-bold text-ink-900">삭제한 핀</span>
            <span className="rounded-md border border-brand-600 px-1.5 py-0.5 text-label font-bold text-link">되돌리기</span>
          </div>
        </At>
      )}
      <PingoAt x={16} y={96} w={24} mood={phase === 3 ? 'relieved' : phase >= 1 ? 'flustered' : 'default'} />
    </>
  )
}

/**
 * 「지도 쓰는 법」(#1613) — 마우스: ① 빈 곳(공원)을 클릭 → ② 그 자리가 가운데로 → ③ 다른 곳을 우클릭 → 누른 자리 점 + 메뉴
 * → ④ 「신규 핀 찍기」 → ⑤ 그 자리에 핀. 터치는 클릭이 짧게 누르기, 우클릭이 길게 누르기(원이 차오름) + 위 말풍선이다.
 * 지도 판(`layer`)이 통째로 옮겨 간다 — 판 밖까지 그려 두어 옮겨도 가장자리가 비지 않는다.
 */
const GESTURE_PHASES = [800, 300, 900, 700, 700, 700, 300, 1400, 600, 900, 900, 400]
/** 처음 누르는 곳(공원)과 옮긴 뒤 핀을 찍는 곳(판 %). */
const TAP: [number, number] = [64, 30]
const MENU_AT: [number, number] = [32, 62]
const SHIFT: [number, number] = [50 - TAP[0], 50 - TAP[1]]
const POINTER_LABEL = { mouse: ['클릭', '우클릭', '눌러서 끌기'], touch: ['짧게 누르기', '길게 누르기', '길게 눌러 끌기'] }
const TRASH_AT: [number, number] = [50, 86]

function MapGestureScene({ touch }: { touch: boolean }) {
  // 움직임 줄이기면 핀을 찍은 ⑦에 머문다.
  const phase = usePhaseLoop(GESTURE_PHASES, 7)
  const moved = phase >= 2 && phase < 11
  // 우클릭은 누르자마자, 길게 누르기는 원이 다 찬 뒤(⑤)에 뜬다.
  const menuOpen = phase >= (touch ? 5 : 4) && phase <= 6
  const [tapX, tapY] = TAP
  const [mx, my] = MENU_AT
  // 핀은 옮겨 간 판 위의 자리라 판 좌표로 적는다.
  const pinInLayer: [number, number] = [mx - SHIFT[0], my - SHIFT[1]]
  // 손(커서·손가락)이 있는 곳과 보일지. 메뉴 단추는 마우스는 누른 자리 오른쪽 아래, 터치는 위 말풍선이다.
  const press: [number, number] = touch ? [mx, my - 13] : [mx + 14, my + 8]
  const grab: [number, number] = [mx, my - 6]
  const hand: [number, number] = phase <= 2 ? TAP : phase === 5 || phase === 6 ? press : phase === 8 ? grab : phase === 9 ? [TRASH_AT[0], TRASH_AT[1] - 6] : MENU_AT
  const handShown = (touch ? phase <= 1 || phase === 3 || phase === 4 || phase === 6 : phase <= 6) || phase === 8 || phase === 9
  const labels = POINTER_LABEL[touch ? 'touch' : 'mouse']
  const label = phase === 1 ? labels[0] : phase === 4 ? labels[1] : phase === 8 ? labels[2] : null
  return (
    <div className={`absolute inset-0 transition-opacity duration-300 motion-reduce:transition-none ${phase === 11 ? 'opacity-0' : ''}`}>
      <div
        className={`absolute inset-0 ${phase === 2 ? 'transition-transform duration-500 ease-out motion-reduce:transition-none' : ''}`}
        style={{ transform: moved ? `translate(${SHIFT[0]}%, ${SHIFT[1]}%)` : undefined }}
      >
        <svg viewBox="0 0 320 240" overflow="visible" className="absolute inset-0 size-full">
          <rect x="-320" y="-240" width="960" height="720" fill="var(--ink-100)" />
          <path d="M-320 250L640 58V76L-320 268Z" fill="#fff" />
          <rect x="90" y="-240" width="14" height="720" fill="#fff" />
          {/* 누르는 곳 — 공원. 옮기면 판 가운데에 온다. */}
          <rect x={tapX * 3.2 - 26} y={tapY * 2.4 - 18} width="52" height="36" rx="12" fill="#CFE8C9" />
        </svg>
        <At x={30} y={48}>
          <ScenePin />
        </At>
        {phase >= 7 && phase <= 9 && (
          <At x={pinInLayer[0]} y={pinInLayer[1]} className={phase >= 8 ? 'opacity-40' : ''}>
            <div className={phase === 7 ? 'enter-drop' : ''}>
              <ScenePin />
            </div>
          </At>
        )}
      </div>
      {(phase === 9 || phase === 10) && (
        <At x={TRASH_AT[0]} y={TRASH_AT[1]} anchor="center">
          <span className={`enter-pop flex items-center gap-1 rounded-full bg-surface px-2.5 py-1 text-label font-bold text-ink-900 shadow-float ${phase === 10 ? 'ring-2 ring-[var(--bad-line)]' : ''}`}>
            <Trash2 size={12} aria-hidden="true" /> 삭제하기
          </span>
        </At>
      )}
      {(phase === 8 || phase === 9) && (
        <At x={hand[0]} y={hand[1] + 6} className={phase === 9 ? 'transition-[left,top] duration-700 ease-in-out motion-reduce:transition-none' : ''}>
          <div className="scale-110">
            <ScenePin />
          </div>
        </At>
      )}
      {menuOpen && (
        <At x={mx} y={my} anchor="center">
          <span className="enter-pop block size-3 rounded-full border-2 border-white bg-brand-600 shadow-float" />
        </At>
      )}
      {menuOpen && (
        <At x={touch ? mx : mx + 2} y={touch ? my - 5 : my + 3} anchor={touch ? 'bottom' : 'top-left'}>
          <span
            className={`btn-outline btn-sm enter-pop pointer-events-none whitespace-nowrap shadow-float transition-transform duration-150 motion-reduce:transition-none ${
              phase === 6 ? 'scale-95' : ''
            }`}
          >
            신규 핀 찍기
          </span>
        </At>
      )}
      {touch && phase === 4 && (
        <At x={mx} y={my} anchor="center" className="size-0">
          <svg viewBox="0 0 48 48" className="press-ring">
            <circle cx="24" cy="24" r="16" pathLength="100" />
          </svg>
        </At>
      )}
      {handShown && (
        <At
          x={hand[0]}
          y={hand[1]}
          anchor={touch ? 'center' : 'top-left'}
          className={`z-10 ${!touch || phase === 9 ? `transition-[left,top] ${phase === 9 ? 'duration-700' : 'duration-500'} ease-in-out motion-reduce:transition-none` : ''}`}
        >
          {touch ? (
            <span
              key={phase === 9 ? 8 : phase}
              className={`enter-fade block size-7 rounded-full border-2 border-white bg-ink-900/30 transition-transform duration-150 motion-reduce:transition-none ${
                phase === 1 || phase === 6 ? 'scale-75' : ''
              }`}
            />
          ) : (
            <svg viewBox="0 0 16 22" width="16" height="22" className={`transition-transform duration-150 motion-reduce:transition-none ${phase === 1 || phase === 4 || phase === 6 ? 'scale-90' : ''}`}>
              <path d="M1 1V17L5.2 13.2L8 20L10.6 18.9L7.9 12.4H13.6Z" fill="var(--ink-900)" stroke="#fff" strokeWidth="1.5" strokeLinejoin="round" />
            </svg>
          )}
          {label && (
            <span className="enter-pop absolute left-full top-full ml-1 whitespace-nowrap rounded-md bg-[var(--toast-bg)] px-1.5 py-0.5 text-label font-bold text-white">
              {label}
            </span>
          )}
        </At>
      )}
      <PingoAt x={86} y={96} w={22} mood={phase === 7 ? 'excited' : 'default'} />
    </div>
  )
}
