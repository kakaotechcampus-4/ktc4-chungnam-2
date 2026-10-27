import { useSyncExternalStore } from 'react'

/** 넓은 화면(태블릿·PC) 기준. Tailwind `md`(768px)와 같은 값이다(#338). */
export const DESKTOP_QUERY = '(min-width: 768px)'

/** PC 기준. Tailwind `lg`(1024px)와 같은 값이다. 768~1023px은 태블릿이다(#603). */
const PC_QUERY = '(min-width: 1024px)'

function media(query: string) {
  return {
    get: () => window.matchMedia(query).matches,
    subscribe: (onChange: () => void) => {
      const mq = window.matchMedia(query)
      mq.addEventListener('change', onChange)
      return () => mq.removeEventListener('change', onChange)
    },
  }
}

const desktop = media(DESKTOP_QUERY)
const pc = media(PC_QUERY)

/** React 바깥(지도 컨트롤러·마커 레이어)에서 부르는 순간의 값. */
export const isDesktopNow = desktop.get

/**
 * 넓은 화면(태블릿·PC)이면 true. 드래그를 끄거나 `hidden` 을 무시하는 건 `md:` 클래스만으로 안 돼서 JS 로 나눈다.
 * 첫 렌더부터 실제 값이라 모바일 화면이 한 번 그려졌다가 바뀌지 않는다.
 */
export function useIsDesktop() {
  return useSyncExternalStore(desktop.subscribe, desktop.get)
}

/** PC(1024px 이상)면 true. 태블릿과는 왼쪽 패널 폭만 다르다(#603). */
export function useIsPc() {
  return useSyncExternalStore(pc.subscribe, pc.get)
}
