import { useEffect, useState } from 'react'

import OfflineState from './OfflineState'
import Pingo, { type PingoMood } from './Pingo'
import { useOnline } from './useOnline'

/** 이보다 빨리 오는 응답엔 아무것도 띄우지 않는다 — 핑고가 잠깐 번쩍이면 오히려 거슬린다. */
const SHOW_AFTER_MS = 1000

/**
 * 응답을 기다리는 로딩(시안 WALK CYCLE) — 뒤뚱뒤뚱 걷는 핑고 + 무엇을 기다리는지 한 줄.
 * 들어설 모양을 아는 목록은 CardSkeleton 을 쓰고, 이건 무엇이 나올지 모르는 기다림(화면 전체·지도·AI 조건 정리)에 쓴다.
 * 로그인 상태 확인만 우주복 핑고(`space`)다 — 배포 중이면 30초까지 걸려서, 걷는 것보다 느긋한 그림을 둔다.
 */
export default function PingoLoading({ label, className = '', mood = 'walk' }: { label: string; className?: string; mood?: Extract<PingoMood, 'walk' | 'space'> }) {
  const [shown, setShown] = useState(false)
  const online = useOnline()
  useEffect(() => {
    const t = setTimeout(() => setShown(true), SHOW_AFTER_MS)
    return () => clearTimeout(t)
  }, [])
  // 끊기면 요청이 멈춰 있어 핑고가 끝없이 걷는다(#1722).
  if (!online) {
    return (
      <div className={`flex flex-col ${className}`}>
        <OfflineState />
      </div>
    )
  }
  return (
    <div role="status" className={`flex flex-col items-center gap-2 py-6 text-center ${className}`}>
      {shown ? (
        <>
          <Pingo size={mood === 'space' ? 72 : 56} mood={mood} />
          <p className="text-sm text-ink-500">{label}</p>
        </>
      ) : (
        <span className="sr-only">{label}</span>
      )}
    </div>
  )
}
