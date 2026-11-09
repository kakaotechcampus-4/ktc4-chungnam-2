import type { ReactNode } from 'react'

/**
 * 말풍선(#1704, 툴팁) — 누른 자리 바로 옆에 짧게 알리는 어두운 풍선. 토스트와 같은 면(`--toast-bg`) + 흰 13/500 글자 + 꼬리.
 * 부르는 쪽의 `relative` 틀 안에 놓고, 사라지는 때도 부르는 쪽이 정한다(몇 초 뒤). 화면 읽기에는 status 로 읽힌다.
 * - `side`: 틀 위(`top`) 또는 아래(`bottom`)
 * - `align`: 틀 가운데(`center`) 또는 오른쪽 끝(`end`, 꼬리는 오른쪽에서 20px)
 */
export default function TipBubble({ side = 'top', align = 'center', children }: { side?: 'top' | 'bottom'; align?: 'center' | 'end'; children: ReactNode }) {
  const place = `${side === 'top' ? 'bottom-full mb-2' : 'top-full mt-2'} ${align === 'center' ? 'left-1/2 -translate-x-1/2' : 'right-0'}`
  const tail = `${side === 'top' ? 'top-full rotate-180' : 'bottom-full'} ${align === 'center' ? 'left-1/2 -ml-[6px]' : 'right-[14px]'}`
  return (
    <span role="status" className={`enter-pop pointer-events-none absolute z-50 w-max max-w-[240px] rounded-xl bg-[var(--toast-bg)] px-3 py-2 text-xs font-medium text-white shadow-float ${place}`}>
      <span className="block break-keep text-center leading-snug">{children}</span>
      {/* 꼬리 — 겹치는 네모 대신 세모라 반투명 면이 겹쳐 진해지지 않는다. */}
      <svg aria-hidden="true" width="12" height="6" viewBox="0 0 12 6" className={`absolute ${tail}`}>
        <path d="M0 6 6 0l6 6z" fill="var(--toast-bg)" />
      </svg>
    </span>
  )
}
