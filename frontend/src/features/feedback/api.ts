import { api } from '@/api'

import type { FeedbackRequest } from './model'

/** 서비스 피드백(#10). 저장만 하고 답장·알림은 없다. */
export const sendFeedback = (body: FeedbackRequest) => api<unknown>('/feedback', { method: 'POST', body: JSON.stringify(body) })
