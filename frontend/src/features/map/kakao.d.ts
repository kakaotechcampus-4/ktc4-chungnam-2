/**
 * 카카오맵 JS SDK 중 실제로 쓰는 표면만 선언한다.
 * 공식 타입 패키지가 없고, 전체를 옮겨 적으면 안 쓰는 API 까지 우리가 유지보수하게 된다.
 * 필요한 API 가 생기면 그때 여기에 한 줄씩 늘린다.
 * 문서: https://apis.map.kakao.com/web/documentation/
 *
 * 이 파일에는 import/export 를 넣지 않는다 — 넣는 순간 모듈이 되어 전역 선언이 사라진다.
 */
declare namespace kakao.maps {
  class LatLng {
    constructor(lat: number, lng: number)
    getLat(): number
    getLng(): number
  }

  /** 지도 틀 안의 픽셀 좌표. */
  class Point {
    constructor(x: number, y: number)
    x: number
    y: number
  }

  interface MapProjection {
    containerPointFromCoords(latlng: LatLng): Point
    coordsFromContainerPoint(point: Point): LatLng
  }

  class LatLngBounds {
    constructor()
    extend(latlng: LatLng): void
    isEmpty(): boolean
  }

  class Map {
    constructor(container: HTMLElement, options: { center: LatLng; level?: number })
    /** 여백(px) 안쪽으로 맞춘다 — 위·오른쪽·아래·왼쪽. */
    setBounds(bounds: LatLngBounds, paddingTop?: number, paddingRight?: number, paddingBottom?: number, paddingLeft?: number): void
    setCenter(latlng: LatLng): void
    panTo(latlng: LatLng): void
    /** 지도 가운데를 픽셀만큼 옮긴다. */
    panBy(dx: number, dy: number): void
    getCenter(): LatLng
    getProjection(): MapProjection
    /** 지도 틀 크기를 CSS 로 바꾼 뒤 부른다. 창 크기 변경(resize)에는 SDK 가 알아서 부른다. */
    relayout(): void
  }

  namespace event {
    function addListener(target: Map, type: 'dragstart' | 'idle', handler: () => void): void
    function removeListener(target: Map, type: 'dragstart' | 'idle', handler: () => void): void
  }

  class CustomOverlay {
    constructor(options: {
      position: LatLng
      content: HTMLElement | string
      /** 1 = 콘텐츠 아래쪽이 좌표에 붙는다. 핀은 뾰족한 끝이 좌표를 가리켜야 한다. */
      yAnchor?: number
      xAnchor?: number
      zIndex?: number
      clickable?: boolean
    })
    setMap(map: Map | null): void
    setZIndex(zIndex: number): void
  }

  class Polyline {
    constructor(options: { path: LatLng[]; strokeWeight?: number; strokeColor?: string; strokeOpacity?: number; strokeStyle?: string })
    setMap(map: Map | null): void
  }

  /** autoload=false 로 받은 SDK 를 실제로 초기화한다. */
  function load(callback: () => void): void
}

interface Window {
  kakao?: { maps?: typeof kakao.maps }
}
