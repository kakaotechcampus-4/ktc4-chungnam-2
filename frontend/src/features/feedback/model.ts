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
 * errors.md의 RATE_LIMITED 문구는 장소 검색용이라 피드백은 여기서 따로 적는다.
 */
export function feedbackErrorMessage(err: unknown): string {
  if (err instanceof ApiError && err.code === 'RATE_LIMITED') return '의견을 너무 자주 보냈어요. 잠시 뒤 다시 보내 주세요'
  return '의견을 보내지 못했어요'
}
