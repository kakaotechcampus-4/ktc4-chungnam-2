import { useEffect, useState } from 'react'

/** 아무것도 안 한 지 이만큼 지나면 지도 위 핑고가 졸고, 조금 더 지나면 이불을 덮고 잔다. */
export const DROWSY_AFTER_MS = 5 * 60_000
export const SLEEP_AFTER_MS = DROWSY_AFTER_MS + 10_000
const CHECK_MS = 1_000
const ACTIVITY = ['pointerdown', 'pointermove', 'keydown', 'wheel', 'touchstart'] as const

export type IdleStage = 'drowsy' | 'sleep' | null

/**
 * 사용자가 화면에서 아무것도 안 한 시간에 따라 핑고의 쉬는 모습(#1433 후속). 손·마우스·키보드가 움직이면 바로 깬다.
 * 화면 장식이라 서버에 알리지 않고 이 창 안에서만 센다.
 */
export function useIdleStage(): IdleStage {
  const [stage, setStage] = useState<IdleStage>(null)
  useEffect(() => {
    let last = Date.now()
    const wake = () => {
      last = Date.now()
      setStage(null)
    }
    const tick = () => {
      const idle = Date.now() - last
      setStage(idle >= SLEEP_AFTER_MS ? 'sleep' : idle >= DROWSY_AFTER_MS ? 'drowsy' : null)
    }
    const timer = setInterval(tick, CHECK_MS)
    for (const e of ACTIVITY) window.addEventListener(e, wake, { passive: true, capture: true })
    return () => {
      clearInterval(timer)
      for (const e of ACTIVITY) window.removeEventListener(e, wake, { capture: true })
    }
  }, [])
  return stage
}
