import { useEffect, useState } from 'react'

/** 움직임 줄이기 설정인지. 테스트(jsdom)처럼 matchMedia 가 없으면 움직이는 쪽으로 본다. */
function prefersStill() {
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/**
 * 온보딩 장면의 단계 — `durations[i]` 만큼 머문 뒤 다음 단계로, 끝나면 처음으로 되풀이한다.
 * 움직임 줄이기면 돌지 않고 `rest` 단계(그 기능을 다 쓴 모습, 기본은 마지막)에 머문다.
 * `durations` 는 모듈 상수로 넘긴다 — 렌더마다 새 배열이면 타이머가 매번 다시 걸린다.
 */
export function usePhaseLoop(durations: readonly number[], rest = durations.length - 1): number {
  const [still] = useState(prefersStill)
  const [phase, setPhase] = useState(0)

  useEffect(() => {
    if (still) return
    const timer = setTimeout(() => setPhase((p) => (p + 1) % durations.length), durations[phase])
    return () => clearTimeout(timer)
  }, [phase, still, durations])

  return still ? rest : phase
}
