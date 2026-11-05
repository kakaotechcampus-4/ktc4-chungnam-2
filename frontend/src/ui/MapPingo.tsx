import { useId } from 'react'

import back from '@/assets/pingo/back.png'
import front from '@/assets/pingo/front.png'
import walk1 from '@/assets/pingo/walk-1.png'
import walk2 from '@/assets/pingo/walk-2.png'
import walk3 from '@/assets/pingo/walk-3.png'
import wave from '@/assets/pingo/wave.png'
import type { MapHeading } from '@/features/shell/sheetStore'

// 처음 끌 때 걷는 그림이 늦게 떠 깜빡이지 않게 미리 받아 둔다.
for (const src of [back, walk1, walk2, walk3, wave]) new Image().src = src

const IMG = 'absolute inset-0 size-full select-none'

/** 사다리(2.5D 나무). 핑고 뒤에 서고, 가로대가 한 칸씩 흘러 오르내리는 것을 보인다. 위·아래로 흐려져 끝이 없다. */
function Ladder({ down }: { down: boolean }) {
  const id = useId()
  return (
    <svg viewBox="0 0 48 72" className="absolute -top-1/4 left-0 h-[150%] w-full overflow-visible">
      <defs>
        <linearGradient id={`${id}r`} x1="0" x2="1">
          <stop offset="0" style={{ stopColor: 'var(--ladder-light)' }} />
          <stop offset="1" style={{ stopColor: 'var(--ladder-dark)' }} />
        </linearGradient>
        <linearGradient id={`${id}g`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" style={{ stopColor: 'var(--ladder-light)' }} />
          <stop offset="1" style={{ stopColor: 'var(--ladder-dark)' }} />
        </linearGradient>
        <linearGradient id={`${id}f`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="white" stopOpacity="0" />
          <stop offset="0.2" stopColor="white" />
          <stop offset="0.85" stopColor="white" />
          <stop offset="1" stopColor="white" stopOpacity="0" />
        </linearGradient>
        <mask id={`${id}m`}>
          <rect width="48" height="72" fill={`url(#${id}f)`} />
        </mask>
      </defs>
      <g mask={`url(#${id}m)`}>
        <g className={`motion-safe:animate-ladder-rungs ${down ? '[animation-direction:reverse]' : ''}`}>
          {Array.from({ length: 8 }, (_, i) => (
            <rect key={i} x="6" y={i * 12 - 10} width="36" height="3.2" rx="1.4" fill={`url(#${id}g)`} />
          ))}
        </g>
        <rect x="4" y="0" width="3.6" height="72" rx="1.6" fill={`url(#${id}r)`} />
        <rect x="40.4" y="0" width="3.6" height="72" rx="1.6" fill={`url(#${id}r)`} />
      </g>
    </svg>
  )
}

/** 새 조언이 있다는 표시(2.5D 「!」 말풍선). 핑고 머리 오른쪽 위에 떠서 천천히 들썩인다. 색은 새 소식 귤색이다. */
function AlertBubble() {
  const id = useId()
  return (
    <svg viewBox="0 0 24 24" className="enter-pop absolute -right-[18%] -top-[8%] size-[46%] overflow-visible drop-shadow-[0_1.5px_1.5px_rgba(31,28,25,0.3)]">
      <defs>
        <radialGradient id={id} cx="0.35" cy="0.3" r="0.75">
          <stop offset="0" style={{ stopColor: 'var(--notify-light)' }} />
          <stop offset="0.55" style={{ stopColor: 'var(--notify-dot)' }} />
          <stop offset="1" style={{ stopColor: 'var(--notify-deep)' }} />
        </radialGradient>
      </defs>
      <g className="origin-bottom-left [transform-box:fill-box] motion-safe:animate-pingo-bob">
        <path d="M12 2a9 9 0 1 1-4.7 16.7L3 21l1.6-4.6A9 9 0 0 1 12 2z" fill={`url(#${id})`} />
        <ellipse cx="9" cy="6.4" rx="4" ry="2" fill="white" opacity="0.5" />
        <rect x="10.7" y="5.6" width="2.6" height="7.4" rx="1.3" fill="white" />
        <circle cx="12" cy="15.9" r="1.5" fill="white" />
      </g>
    </svg>
  )
}

/**
 * 지도 위 핑고(#1433) — 디자이너 3D 렌더(원본 144px). 시트·패널 안은 평면 `Pingo`다(3D가 겉돈다, DESIGN.md 「핑고」).
 * heading 이 있으면 그쪽으로 움직인다. 좌우는 측면 걷기 1·2·3·2(원본은 오른쪽으로 걷는 모습이라 왼쪽은 뒤집는다)로 걷고,
 * 위·아래는 뒤를 돌아 사다리를 오르내린다 — 뒷모습과 뒤집은 뒷모습을 걸음마다 바꿔 팔을 번갈아 뻗고, 가로대가 한 칸씩 흐른다.
 * 서 있으면 정면이고 `wave`·`alert` 면 손을 흔든다. `alert`(새 조언)면 머리 옆에 「!」 말풍선이 뜬다.
 * 크기는 부르는 쪽 className 으로 준다. 움직임 줄이기면 그쪽을 보기만 하고 움직이지 않는다.
 */
export default function MapPingo({ heading, wave: waving = false, alert = false, className = '' }: { heading: MapHeading | null; wave?: boolean; alert?: boolean; className?: string }) {
  const vertical = heading === 'up' || heading === 'down'
  return (
    <span aria-hidden="true" className={`relative block ${className}`}>
      {vertical && <Ladder down={heading === 'down'} />}
      {heading === 'left' || heading === 'right' ? (
        <span className={`absolute inset-0 motion-safe:animate-pingo-walk ${heading === 'left' ? '-scale-x-100' : ''}`}>
          <img src={walk1} alt="" draggable={false} className={`${IMG} motion-safe:animate-pingo-frame-a`} />
          <img src={walk2} alt="" draggable={false} className={`${IMG} opacity-0 motion-safe:animate-pingo-frame-b`} />
          <img src={walk3} alt="" draggable={false} className={`${IMG} opacity-0 motion-safe:animate-pingo-frame-a motion-safe:[animation-delay:-300ms]`} />
        </span>
      ) : vertical ? (
        <span className={`absolute inset-0 ${heading === 'up' ? 'motion-safe:animate-pingo-climb' : 'motion-safe:animate-pingo-descend'}`}>
          <img src={back} alt="" draggable={false} className={`${IMG} motion-safe:animate-pingo-frame-half`} />
          <img src={back} alt="" draggable={false} className={`${IMG} -scale-x-100 opacity-0 motion-safe:animate-pingo-frame-half motion-safe:[animation-delay:-300ms]`} />
        </span>
      ) : (
        <img src={waving || alert ? wave : front} alt="" draggable={false} className={IMG} />
      )}
      {alert && <AlertBubble />}
    </span>
  )
}
