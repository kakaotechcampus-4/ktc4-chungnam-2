import { useMutation } from '@tanstack/react-query'

import { sendFeedback } from './api'
import type { FeedbackRequest } from './model'

export function useSendFeedbackMutation() {
  return useMutation({ mutationFn: (body: FeedbackRequest) => sendFeedback(body) })
}
