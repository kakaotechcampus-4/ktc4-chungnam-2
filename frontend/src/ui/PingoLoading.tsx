import { useEffect, useState } from 'react'

import Pingo from './Pingo'

/** 이보다 빨리 오는 응답엔 아무것도 띄우지 않는다 — 핑고가 잠깐 번쩍이면 오히려 거슬린다. */
const SHOW_AFTER_MS = 1000

/**
 * 응답을 기다리는 로딩(시안 WALK CYCLE) — 뒤뚱뒤뚱 걷는 핑고 + 무엇을 기다리는지 한 줄.
 * 들어설 모양을 아는 목록은 CardSkeleton 을 쓰고, 이건 무엇이 나올지 모르는 기다림(화면 전체·지도·AI 조건 정리)에 쓴다.
 */
export default function PingoLoading({ label, className = '' }: { label: string; className?: string }) {
  const [shown, setShown] = useState(false)
  useEffect(() => {
    const t = setTimeout(() => setShown(true), SHOW_AFTER_MS)
    return () => clearTimeout(t)
  }, [])
  return (
    <div role="status" className={`flex flex-col items-center gap-2 py-6 text-center ${className}`}>
      {shown ? (
        <>
          <Pingo size={56} mood="walk" />
          <p className="text-sm text-ink-500">{label}</p>
        </>
      ) : (
        <span className="sr-only">{label}</span>
      )}
    </div>
  )
}
