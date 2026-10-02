import type { components } from '@pingo/contracts/src/types/api'

import { ApiError } from '@/api'

export type MapDto = components['schemas']['Map']
export type MapCreateRequest = components['schemas']['MapCreateRequest']

export type MapView = Pick<MapDto, 'id' | 'title'> & {
  /** 목록 한 줄 요약 — "2026-10-03 ~ 2026-10-05 · 3명" */
  summary: string
}

export function toMapView(map: MapDto): MapView {
  return {
    id: map.id,
    title: map.title,
    summary: `${map.start_date} ~ ${map.end_date} · ${map.member_count}명`,
  }
}

/** 목 서버·BE 모두 없는 토큰에 401/404 를 준다. 로그인은 화면에서 이미 확인했으니 링크 문제다. */
export function inviteErrorMessage(err: unknown): string {
  return err instanceof ApiError && ['UNAUTHORIZED', 'NOT_FOUND'].includes(err.code)
    ? '초대 링크가 유효하지 않거나 만료됐어요'
    : '참여하지 못했어요'
}
