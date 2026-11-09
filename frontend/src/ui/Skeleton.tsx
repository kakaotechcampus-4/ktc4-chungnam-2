import { useEffect, useState, type ReactNode } from 'react'

/** 뼈대 한 칸 — 글줄·칩·칸 자리. 크기와 모양(반경)은 부르는 쪽이 `className`으로 준다(`h-4 w-2/3`, `h-8 w-20 rounded-full`). */
export function Bone({ className = '' }: { className?: string }) {
  return <div className={`rounded-sm bg-ink-100 ${className}`} />
}

/**
 * 스켈레톤(#1675, 로딩 패턴 「스켈레톤」) — 무엇이 나올지 모양을 아는 기다림에서, 글자 대신 그 모양 자리를 먼저 그린다.
 * 모양은 화면 읽기에 숨기고 `label`만 화면 읽기에 알린다. 동작 줄이기면 깜박이지 않는다.
 * 모양을 모르는 기다림(로그인·초대 확인, 지도 불러오기)은 `PingoLoading`, 받았는데 0개면 `EmptyState`다 — 빈 화면에 스켈레톤을 두면 아직 오는 중으로 읽힌다.
 */
export default function Skeleton({
  label,
  className = '',
  delayMs = 0,
  children,
}: {
  label?: string
  className?: string
  /** 이만큼 지나도 못 받았을 때만 그린다. 금방 오는 응답에 뼈대가 번쩍였다 사라지며 아래 내용을 두 번 밀지 않게(핀 상세 장소 후기). */
  delayMs?: number
  children: ReactNode
}) {
  const [shown, setShown] = useState(delayMs === 0)
  useEffect(() => {
    if (delayMs === 0) return
    const t = setTimeout(() => setShown(true), delayMs)
    return () => clearTimeout(t)
  }, [delayMs])
  if (!shown) return null
  return (
    <>
      {label && (
        <p role="status" className="sr-only">
          {label}
        </p>
      )}
      <div aria-hidden="true" className={`animate-pulse motion-reduce:animate-none ${className}`}>
        {children}
      </div>
    </>
  )
}
