import type { components } from '@pingo/contracts/src/types/api'

import { ApiError } from '@/api'

export type FeedbackRequest = components['schemas']['FeedbackRequest']
export type FeedbackCategory = NonNullable<FeedbackRequest['category']>

export const FEEDBACK_CATEGORIES: { key: FeedbackCategory; label: string }[] = [
  { key: 'bug', label: '버그' },
  { key: 'idea', label: '아이디어' },
  { key: 'other', label: '기타' },
]

/**
 * 보내기 실패 문구(docs/errors.md 코드별). 상한 횟수는 서버 설정이라 화면에 숫자를 적지 않는다.
 * RATE_LIMITED 문구는 errors.md의 장소 검색 문장을 따르고 동작만 「보내고」로 바꾼다.
 */
export function feedbackErrorMessage(err: unknown): string {
  if (err instanceof ApiError && err.code === 'RATE_LIMITED') return '너무 자주 보내고 있어요. 잠시 뒤 다시 시도해 주세요'
  return '의견을 보내지 못했어요'
}
