import back from '@/assets/pingo/back.png'
import diagDownLeft from '@/assets/pingo/diag-down-left.png'
import diagDownRight from '@/assets/pingo/diag-down-right.png'
import diagUpLeft from '@/assets/pingo/diag-up-left.png'
import diagUpRight from '@/assets/pingo/diag-up-right.png'
import drowsy from '@/assets/pingo/drowsy.png'
import front from '@/assets/pingo/front.png'
import sleep from '@/assets/pingo/sleep.png'
import walk1 from '@/assets/pingo/walk-1.png'
import walk2 from '@/assets/pingo/walk-2.png'
import walk3 from '@/assets/pingo/walk-3.png'
import walkLeft1 from '@/assets/pingo/walk-left-1.png'
import walkLeft2 from '@/assets/pingo/walk-left-2.png'
import walkLeft3 from '@/assets/pingo/walk-left-3.png'
import wave from '@/assets/pingo/wave.png'
import type { IdleStage } from '@/features/agent/useIdleStage'
import type { MapHeading } from '@/features/shell/sheetStore'

// 처음 끌 때 걷는 그림이 늦게 떠 깜빡이지 않게 미리 받아 둔다.
for (const src of [back, diagDownLeft, diagDownRight, diagUpLeft, diagUpRight, walk1, walk2, walk3, walkLeft1, walkLeft2, walkLeft3, wave, drowsy, sleep]) new Image().src = src

const IMG = 'absolute inset-0 size-full select-none'
const DIAGONAL = { 'up-left': diagUpLeft, 'up-right': diagUpRight, 'down-left': diagDownLeft, 'down-right': diagDownRight }

/** 잘 때 덮는 이불 — 3D 그림(144px)과 같은 좌표에서 팔과 몸 아래쪽을 덮는다. 접어 내린 단은 밝게, 아래로 갈수록 진하게 해 둥글게 보인다. */
function Blanket() {
  return (
    <svg viewBox="0 0 144 144" className="enter-fade absolute inset-0 size-full">
      <defs>
        <linearGradient id="pingo-blanket" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" style={{ stopColor: 'var(--brand-200)' }} />
          <stop offset="1" style={{ stopColor: 'var(--brand-300)' }} />
        </linearGradient>
      </defs>
      <path d="M12 108C30 96 52 100 72 98s42-2 60 10c4 14 2 28-12 32H24c-14-4-16-18-12-32z" fill="url(#pingo-blanket)" style={{ stroke: 'var(--brand-400)' }} strokeWidth="1.2" strokeLinejoin="round" />
      <path d="M12 108C30 96 52 100 72 98s42-2 60 10l.8 8C114 105 92 106 72 107s-42 1-60.8 9z" style={{ fill: 'var(--brand-100)', stroke: 'var(--brand-400)' }} strokeWidth="1.2" strokeLinejoin="round" />
      <path d="M48 120c-1 7 0 13 1 19M96 119c1 7 1 14 0 20" fill="none" style={{ stroke: 'var(--brand-400)' }} strokeOpacity=".45" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  )
}

/** 자는 동안 머리 왼쪽 위로 「z」가 차례로 떠오르다 사라진다. */
function Snore() {
  return (
    <svg viewBox="0 0 40 40" className="absolute -left-[6%] top-0 size-[40%] overflow-visible font-bold" style={{ fill: 'var(--ink-500)' }}>
      {[
        { x: 26, y: 36, size: 9, delay: '0s' },
        { x: 15, y: 24, size: 12, delay: '-0.8s' },
        { x: 2, y: 12, size: 15, delay: '-1.6s' },
      ].map((z) => (
        <text key={z.delay} x={z.x} y={z.y} fontSize={z.size} className="[transform-box:fill-box] motion-safe:animate-pingo-snore" style={{ animationDelay: z.delay }}>
          z
        </text>
      ))}
    </svg>
  )
}

/** 옆으로 걷는 그림 1·2·3·2 를 0.15초씩. 왼쪽은 원본을 뒤집고 명암을 오른쪽 빛으로 다시 맞춘 그림이다(#1440 리뷰). */
function SideWalk({ left }: { left: boolean }) {
  const [w1, w2, w3] = left ? [walkLeft1, walkLeft2, walkLeft3] : [walk1, walk2, walk3]
  return (
    <>
      <img src={w1} alt="" draggable={false} className={`${IMG} motion-safe:animate-pingo-frame-a`} />
      <img src={w2} alt="" draggable={false} className={`${IMG} opacity-0 motion-safe:animate-pingo-frame-b`} />
      <img src={w3} alt="" draggable={false} className={`${IMG} opacity-0 motion-safe:animate-pingo-frame-a motion-safe:[animation-delay:-300ms]`} />
    </>
  )
}

/**
 * 지도 위 핑고(#1433) — 디자이너 3D 렌더(원본 144px). 시트·패널 안은 평면 `Pingo`다(3D가 겉돈다, DESIGN.md 「핑고」).
 * heading 이 있으면 그쪽(8방향)으로 움직인다.
 * - 좌우: 측면 걷기 1·2·3·2, 걸음마다 들썩인다.
 * - 위: 뒤를 돌아 걸음마다 몸이 한 번 오르고 좌우로 살짝 기운다. 원본 뒷모습 한 장만 쓴다 —
 *   뒤집은 뒷모습을 번갈아 쓰면 하이라이트와 가장자리 그늘이 걸음마다 좌우로 바뀌었다.
 * - 아래: 정면으로 걸음마다 한 칸씩 내려온다. 사용자 쪽으로 오는 방향이라 ↙·↘(반측면)처럼 얼굴이 보인다.
 * - 대각선: 반측면 그림이 그쪽을 보고 위·아래처럼 걷는다. 원본 반측면(`01_반측면`)이 오른쪽 아래이고, 왼쪽은 뒤집어 빛을 다시 맞춘 그림,
 *   위쪽 둘은 눈을 지운 그림이다 — 몸이 둥글고 좌우가 같아서 반대쪽 아래를 보는 모습을 뒤에서 본 모양이 된다(`~/ktc4-drafts-review/pingo-diagonals.py`).
 * 원본 렌더의 빛은 오른쪽 위다. 서 있으면 정면이고 `wave` 면 손을 흔든다.
 * `idle` 이면 쉰다 — 졸 땐 눈을 반쯤 감고 꾸벅이고, 잘 땐 눈을 감고 이불을 덮은 채 숨 쉬며 「z」가 떠오른다.
 * 크기는 부르는 쪽 className 으로 준다. 움직임 줄이기면 그쪽을 보기만 하고(쉴 때는 그 모습으로 서서) 움직이지 않는다.
 */
export default function MapPingo({
  heading,
  wave: waving = false,
  idle = null,
  className = '',
}: {
  heading: MapHeading | null
  wave?: boolean
  idle?: IdleStage
  className?: string
}) {
  const up = heading?.startsWith('up') ?? false
  const down = heading?.startsWith('down') ?? false
  const side = heading === 'left' || heading === 'right' ? heading : null
  const diagonal = heading && heading.includes('-') ? DIAGONAL[heading as keyof typeof DIAGONAL] : null
  const step = up ? 'motion-safe:animate-pingo-climb' : down ? 'motion-safe:animate-pingo-descend' : 'motion-safe:animate-pingo-walk'
  const resting = !heading && idle
  return (
    <span aria-hidden="true" className={`relative block ${className}`}>
      {side ? (
        <span className={`absolute inset-0 ${step}`}>
          <SideWalk left={side === 'left'} />
        </span>
      ) : up || down ? (
        <span className={`absolute inset-0 ${step}`}>
          <img src={diagonal ?? (up ? back : front)} alt="" draggable={false} className={`${IMG} origin-bottom motion-safe:animate-pingo-sway`} />
        </span>
      ) : resting ? (
        <span className={`absolute inset-0 origin-bottom ${idle === 'sleep' ? 'motion-safe:animate-pingo-breathe' : 'motion-safe:animate-pingo-nod'}`}>
          <img src={idle === 'sleep' ? sleep : drowsy} alt="" draggable={false} className={IMG} />
          {idle === 'sleep' && <Blanket />}
        </span>
      ) : (
        <img src={waving ? wave : front} alt="" draggable={false} className={IMG} />
      )}
      {resting === 'sleep' && <Snore />}
    </span>
  )
}
