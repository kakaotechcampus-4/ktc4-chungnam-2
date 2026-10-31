import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { choosePendingAccount, fetchMe, fetchPendingAccount, isNoPendingLogin, isUnauthorized, logout, withdraw } from './api'
import type { PendingAccountDto, User } from './model'

export const authKeys = {
  me: ['me'] as const,
  pending: ['auth', 'pending'] as const,
}

/**
 * 탈퇴 계정 재로그인의 선택 안내(#855). 404 는 다시 물어도 404 다.
 * 콜백에서 돌아올 때마다 새로 묻는다 — 지난번의 404 가 캐시에 남아 있으면 새 선택 화면이 열리자마자 닫힌다.
 */
export function usePendingAccountQuery() {
  return useQuery<PendingAccountDto>({
    queryKey: authKeys.pending,
    queryFn: fetchPendingAccount,
    gcTime: 0,
    retry: (count, err) => !isNoPendingLogin(err) && count < 1,
  })
}

/**
 * 「새 계정으로 시작」·「기존 계정 되살리기」. 응답이 세션 쿠키와 함께 온 `User` 라 그대로 로그인 상태로 둔다.
 * 그 전 캐시는 통째로 비운다 — 게스트로 시작한 로그인이었으면 게스트의 데이터가 남아 있을 수 있다.
 */
export function usePendingChoiceMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: choosePendingAccount,
    onSuccess: (user) => {
      queryClient.clear()
      queryClient.setQueryData(authKeys.me, user)
    },
  })
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
