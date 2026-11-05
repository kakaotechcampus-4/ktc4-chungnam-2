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

/** 새 조언이 있다는 표시 — 평면 「!」 말풍선(AI 색 `--advice-alert`, 흰 테두리). 핑고 머리 오른쪽 위에 떠서 천천히 들썩인다. */
function AlertBubble() {
  return (
    <svg viewBox="0 0 24 24" className="enter-pop absolute -right-[16%] -top-[6%] size-[42%] overflow-visible drop-shadow-[0_1px_2px_rgba(31,28,25,0.25)]">
      <g className="origin-bottom-left [transform-box:fill-box] motion-safe:animate-pingo-bob">
        <path d="M12 2a9 9 0 1 1-4.7 16.7L3 21l1.6-4.6A9 9 0 0 1 12 2z" style={{ fill: 'var(--advice-alert)' }} stroke="white" strokeWidth="2" strokeLinejoin="round" />
        <rect x="10.7" y="5.8" width="2.6" height="7.2" rx="1.3" fill="white" />
        <circle cx="12" cy="15.9" r="1.5" fill="white" />
      </g>
    </svg>
  )
}

/**
 * 지도 위 핑고(#1433) — 디자이너 3D 렌더(원본 144px). 시트·패널 안은 평면 `Pingo`다(3D가 겉돈다, DESIGN.md 「핑고」).
 * heading 이 있으면 그쪽으로 움직인다. 좌우는 측면 걷기 1·2·3·2(원본은 오른쪽으로 걷는 모습이라 왼쪽은 뒤집는다)로 걷고,
 * 위·아래는 뒤를 돌아 오르내린다 — 뒷모습과 뒤집은 뒷모습을 걸음마다 바꿔 팔을 번갈아 뻗고, 걸음마다 몸이 한 번 오르거나 내려간다.
 * 서 있으면 정면이고 `wave`·`alert` 면 손을 흔든다. `alert`(새 조언)면 머리 옆에 「!」 말풍선이 뜬다.
 * 크기는 부르는 쪽 className 으로 준다. 움직임 줄이기면 그쪽을 보기만 하고 움직이지 않는다.
 */
export default function MapPingo({ heading, wave: waving = false, alert = false, className = '' }: { heading: MapHeading | null; wave?: boolean; alert?: boolean; className?: string }) {
  const vertical = heading === 'up' || heading === 'down'
  return (
    <span aria-hidden="true" className={`relative block ${className}`}>
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
