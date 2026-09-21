/**
 * 카카오맵 SDK 로더.
 *
 * `autoload=false` 로 받아서 `kakao.maps.load()` 로 직접 초기화한다 — 자동 로드는
 * 스크립트 태그가 파싱되는 시점에 맞춰 돌기 때문에 React 마운트 시점과 어긋난다.
 */

/** 앱키가 없을 때. 화면이 "지도를 못 그림"과 "키 설정이 빠짐"을 구분해서 안내하려고 따로 세운다. */
export class KakaoMapKeyMissingError extends Error {
  constructor() {
    super('VITE_KAKAO_MAP_KEY 가 없어요')
    this.name = 'KakaoMapKeyMissingError'
  }
}

let pending: Promise<typeof kakao.maps> | null = null

export function loadKakaoMaps(): Promise<typeof kakao.maps> {
  if (pending) return pending

  pending = new Promise<typeof kakao.maps>((resolve, reject) => {
    const appKey = import.meta.env.VITE_KAKAO_MAP_KEY
    if (!appKey) {
      reject(new KakaoMapKeyMissingError())
      return
    }

    // StrictMode 의 이중 마운트나 탭 왕복으로 이미 떠 있는 경우.
    const loaded = window.kakao?.maps
    if (loaded) {
      loaded.load(() => resolve(loaded))
      return
    }

    const script = document.createElement('script')
    script.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${appKey}&autoload=false`
    script.async = true
    script.onload = () => {
      const maps = window.kakao?.maps
      if (!maps) {
        reject(new Error('카카오맵 SDK 를 받았는데 kakao.maps 가 없어요'))
        return
      }
      maps.load(() => resolve(maps))
    }
    // 도메인 미등록·키 오류도 여기로 온다. 조용히 넘기지 않는다.
    script.onerror = () =>
      reject(new Error('카카오맵 SDK 를 불러오지 못했어요 (앱키·플랫폼 도메인 등록 확인)'))
    document.head.appendChild(script)
  })

  // 실패를 캐시하면 새로고침 전까지 영영 재시도가 안 된다.
  pending.catch(() => {
    pending = null
  })

  return pending
}
