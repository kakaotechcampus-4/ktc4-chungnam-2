import type { components } from '@pingo/contracts/src/types/api'

import { ApiError } from '@/api'
import { isLive } from '@/features/map/livePlaces'
import type { Pin } from '@/features/map/model'

export type ReviewPageDto = components['schemas']['ReviewPage']
export type ReviewItemDto = components['schemas']['ReviewItem']
export type MyReviewDto = components['schemas']['MyReview']
export type ReviewSavedDto = components['schemas']['ReviewSaved']
export type ReviewUpsertRequest = components['schemas']['ReviewUpsertRequest']

/**
 * 후기는 자체 DB 장소에 붙는다(docs/credits-reviews.md 5절). 실시간 핀(live)은 서버가 422 PLACE_NOT_SUPPORTED라 영역을 그리지 않는다.
 * source 가 없으면 db 로 본다(api-spec Pin.source) — 판정은 isLive 한 곳이다.
 */
export const hasReviews = (pin: Pin) => !isLive(pin)

/** 작성자 이름은 내리지 않는다(#432 결정 B) — 다른 데서 이름을 찾아 붙이지 않는다. */
export const authorLabel = (item: Pick<ReviewItemDto, 'is_mine'>) => (item.is_mine ? '나' : '핑고 사용자')

/** 머리 줄. 평균은 서버가 소수 첫째 자리로 준다. */
export const summaryText = (summary: ReviewPageDto['summary']) =>
  summary.average_rating === null ? '아직 후기가 없어요' : `${summary.average_rating} · 후기 ${summary.count}개`

/** 저장 뒤 토스트. 처음 쓴 저장이면 받은 크레딧을 알린다(숫자는 응답의 credited). */
export const savedText = (saved: Pick<ReviewSavedDto, 'credited'>) =>
  saved.credited > 0 ? `${saved.credited} 크레딧을 받았어요` : '후기를 저장했어요'

/** 글은 앞뒤 공백을 걷은 뒤 1자 이상. 상한은 입력칸이 limits.body_max로 막는다. */
export const canSave = (rating: number | null, body: string) => rating !== null && body.trim() !== ''

/** 저장 실패 문구(docs/errors.md). 게스트(403)는 부르는 쪽이 카카오 안내로 바꾼다. */
export function saveErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === 'VALIDATION_ERROR') return '별점과 글을 확인해 주세요'
    if (err.code === 'PLACE_NOT_SUPPORTED') return '이 장소에는 후기를 남길 수 없어요'
  }
  return '후기를 저장하지 못했어요'
}

/** 첫 쪽의 요약·상한·내 후기와 모든 쪽의 목록을 하나로. */
export function flattenPages(pages: ReviewPageDto[]) {
  const first = pages[0]
  return { summary: first.summary, limits: first.limits, mine: first.mine, items: pages.flatMap((p) => p.items) }
}
