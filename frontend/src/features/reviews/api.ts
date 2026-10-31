import { api } from '@/api'

import type { ReviewPageDto, ReviewSavedDto, ReviewUpsertRequest } from './model'

/** 그 핀이 가리키는 장소의 후기(#432 D1 — 핀 id로 부르고 서버가 장소를 찾는다). 최신순 20개씩. */
export const fetchReviews = (pinId: string, cursor?: string) =>
  api<ReviewPageDto>(`/pins/${pinId}/reviews${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`)

/** 내 후기 쓰기·고치기. 한 사람이 한 장소에 하나라 같은 주소로 덮는다. */
export const saveMyReview = (pinId: string, body: ReviewUpsertRequest) =>
  api<ReviewSavedDto>(`/pins/${pinId}/reviews/me`, { method: 'PUT', body: JSON.stringify(body) })

export const deleteMyReview = (pinId: string) => api<void>(`/pins/${pinId}/reviews/me`, { method: 'DELETE' })

/** 신고. 이미 했어도 204(멱등). */
export const reportReview = (reviewId: string) => api<void>(`/reviews/${reviewId}/reports`, { method: 'POST' })
