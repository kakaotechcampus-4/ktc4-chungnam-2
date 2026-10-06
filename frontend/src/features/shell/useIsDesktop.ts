import { useSyncExternalStore } from 'react'

/** 넓은 화면 기준. Tailwind `md`(768px)와 같은 값이다(#338). */
export const DESKTOP_QUERY = '(min-width: 768px)'

/** React 바깥(지도 컨트롤러·마커 레이어)에서 부르는 순간의 값. */
export function isDesktopNow() {
  return window.matchMedia(DESKTOP_QUERY).matches
}

function subscribe(onChange: () => void) {
  const mq = window.matchMedia(DESKTOP_QUERY)
  mq.addEventListener('change', onChange)
  return () => mq.removeEventListener('change', onChange)
}

/**
 * 넓은 화면이면 true. 드래그를 끄거나 `hidden` 을 무시하는 건 `md:` 클래스만으로 안 돼서 JS 로 나눈다.
 * 첫 렌더부터 실제 값이라 모바일 화면이 한 번 그려졌다가 바뀌지 않는다.
 */
export function useIsDesktop() {
  return useSyncExternalStore(subscribe, isDesktopNow)
}
