import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query'

import { invalidateCredits } from '@/features/credits/queries'

import { deleteMyReview, fetchReviews, reportReview, saveMyReview } from './api'
import type { ReviewUpsertRequest } from './model'

export const reviewKeys = {
  list: (pinId: string) => ['pins', pinId, 'reviews'] as const,
}

/** 후기 목록. next_cursor 가 있으면 「더 보기」로 다음 쪽을 잇는다. */
export function useReviewsQuery(pinId: string) {
  return useInfiniteQuery({
    queryKey: reviewKeys.list(pinId),
    queryFn: ({ pageParam }) => fetchReviews(pinId, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor,
  })
}

/** 저장하면 목록·평균을 다시 받고, 처음 쓴 저장은 크레딧이 늘었으니 잔액도 다시 받는다(#952 의 키). */
export function useSaveReviewMutation(pinId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: ReviewUpsertRequest) => saveMyReview(pinId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: reviewKeys.list(pinId) })
      void invalidateCredits(queryClient)
    },
  })
}

/** 지워도 받은 크레딧은 그대로라 잔액은 다시 받지 않는다. */
export function useDeleteReviewMutation(pinId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => deleteMyReview(pinId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: reviewKeys.list(pinId) }),
  })
}

export function useReportReviewMutation() {
  return useMutation({ mutationFn: (reviewId: string) => reportReview(reviewId) })
}
