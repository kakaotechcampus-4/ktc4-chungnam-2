import { Outlet } from 'react-router'

import { ApiError } from '@/api'
import { isUnauthorized, kakaoLoginUrl, useMe } from '@/features/auth/auth'

/** 로그인해야 볼 수 있는 화면들을 감싼다. 비로그인이면 그 자리에 로그인 화면을 띄운다. */
export default function RequireLogin() {
  const { isPending, error } = useMe()

  if (isPending) return <p className="p-4 text-sm text-muted-foreground">확인하는 중…</p>
  if (isUnauthorized(error)) return <LoginScreen />
  if (error) {
    return (
      <p className="p-4 text-sm text-destructive">
        로그인 상태를 확인하지 못했어요
        {error instanceof ApiError && <span className="ml-1 font-mono text-xs">({error.code})</span>}
      </p>
    )
  }
  return <Outlet />
}

export function LoginScreen({ message = '같이 갈 곳을 한 지도에 모아요' }: { message?: string }) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-4 p-4">
      <h1 className="text-xl font-semibold">핀고핀고</h1>
      <p className="text-sm text-muted-foreground">{message}</p>
      <a href={kakaoLoginUrl()} className="rounded-md bg-[#FEE500] px-4 py-2 text-sm font-medium text-black">
        카카오로 로그인
      </a>
    </div>
  )
}
