import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { fetchMe, isUnauthorized, logout, withdraw } from './api'
import type { User } from './model'

export const authKeys = {
  me: ['me'] as const,
}

/** 로그인 여부의 정본. 쿠키는 httpOnly 라 프론트가 직접 볼 수 없고, 이 응답이 401 이면 비로그인이다. */
export function useMeQuery() {
  return useQuery<User>({
    queryKey: authKeys.me,
    queryFn: fetchMe,
    // 401 은 다시 물어도 401 이다.
    retry: (count, err) => !isUnauthorized(err) && count < 1,
  })
}

/** 탈퇴도 로그아웃처럼 캐시를 통째로 비운다 — 계정이 사라졌으니 남은 데이터를 화면에 두지 않는다. */
export function useWithdrawMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: withdraw,
    onSuccess: () => queryClient.clear(),
  })
}

/** 로그아웃하면 캐시를 통째로 비운다 — 남의 지도 데이터가 다음 로그인에 잠깐이라도 비치면 안 된다. */
export function useLogoutMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: logout,
    onSuccess: () => queryClient.clear(),
  })
}
