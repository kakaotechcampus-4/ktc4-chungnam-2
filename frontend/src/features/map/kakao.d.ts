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
    /** 부드럽게 옮긴다. 화면보다 먼 거리는 애니메이션 없이 바로 옮긴다. */
    panTo(latlng: LatLng): void
    /** 지도 가운데를 픽셀만큼 옮긴다. */
    panBy(dx: number, dy: number): void
    getCenter(): LatLng
    /** 확대 레벨. 작을수록 가깝다(1 이 가장 가깝다). */
    getLevel(): number
    /** anchor 를 주면 그 좌표가 화면에서 제자리에 있는 채로 확대·축소한다. */
    setLevel(level: number, options?: { animate?: boolean | { duration: number }; anchor?: LatLng }): void
    getProjection(): MapProjection
    /** 지도 틀 크기를 CSS 로 바꾼 뒤 부른다. 창 크기 변경(resize)에는 SDK 가 알아서 부른다. */
    relayout(): void
  }

  namespace event {
    /** click 의 인자 — 누른 자리. dragstart·idle·zoom_changed 는 인자가 없다. */
    type MouseEvent = { latLng: LatLng }
    /** click 은 지도 빈 곳을 눌렀을 때만 온다 — clickable 오버레이(핀 등)를 누르거나 끌고 놓으면 오지 않는다. */
    function addListener(target: Map, type: 'dragstart' | 'idle' | 'click' | 'zoom_changed', handler: (e?: MouseEvent) => void): void
    function removeListener(target: Map, type: 'dragstart' | 'idle' | 'click' | 'zoom_changed', handler: (e?: MouseEvent) => void): void
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

/**
 * 키워드 장소 검색(`libraries=services`). 실시간 핀(#382)의 위치를 지도를 열 때마다 다시 찾는 데만 쓴다.
 * 응답(이름·좌표)은 메모리에서만 쓰고 서버·저장소로 보내지 않는다(카카오 약관, #53).
 */
declare namespace kakao.maps.services {
  type Status = 'OK' | 'ZERO_RESULT' | 'ERROR'

  interface PlaceResult {
    id: string
    place_name: string
    /** 경도 */
    x: string
    /** 위도 */
    y: string
    place_url: string
    address_name: string
    /** 도로명 주소. 없으면 빈 문자열이다. */
    road_address_name: string
  }

  interface Pagination {
    current: number
    last: number
    hasNextPage: boolean
  }

  class Places {
    constructor()
    keywordSearch(
      keyword: string,
      callback: (data: PlaceResult[], status: Status, pagination: Pagination) => void,
      options?: {
        location?: kakao.maps.LatLng
        radius?: number
        page?: number
        size?: number
        sort?: SortBy
        /** 음식점 FD6 · 카페 CE7 · 관광명소 AT4 */
        category_group_code?: string
      },
    ): void
  }

  type SortBy = 'accuracy' | 'distance'
  const SortBy: { ACCURACY: 'accuracy'; DISTANCE: 'distance' }
}
