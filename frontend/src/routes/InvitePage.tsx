import { useEffect } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router'
import type { components } from '@pingo/contracts/src/types/api'

import { api, ApiError } from '@/api'
import {
  clearPendingInvite,
  isUnauthorized,
  savePendingInvite,
  useMe,
} from '@/features/auth/auth'
import { LoginScreen } from '@/features/auth/RequireLogin'

type MapInfo = components['schemas']['Map']

/**
 * 초대 수락 (#4). 비로그인이면 토큰을 들고 로그인으로 보내고, 로그인 후 목록에서 여기로 되돌아온다.
 *
 * 로그인 전 "읽기만"(#23)은 아직 못 한다 — 토큰으로 지도를 미리 볼 수 있는 API 가 스펙에 없다.
 * 지금은 로그인 안내만 띄운다.
 */
export default function InvitePage() {
  const { token = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const me = useMe()
  const loggedIn = Boolean(me.data)
  const needsLogin = isUnauthorized(me.error)

  useEffect(() => {
    if (needsLogin) savePendingInvite(token)
    if (loggedIn) clearPendingInvite()
  }, [needsLogin, loggedIn, token])

  const accept = useMutation({
    mutationFn: () => api<MapInfo>(`/invites/${encodeURIComponent(token)}/accept`, { method: 'POST' }),
    onSuccess: (map) => {
      void queryClient.invalidateQueries({ queryKey: ['maps'] })
      navigate(`/maps/${map.id}`, { replace: true })
    },
  })

  if (me.isPending) return <p className="p-4 text-sm text-muted-foreground">확인하는 중…</p>

  if (needsLogin) {
    return <LoginScreen message="지도에 초대받았어요. 로그인하고 참여하세요" />
  }

  if (me.error) {
    return (
      <p className="p-4 text-sm text-destructive">
        로그인 상태를 확인하지 못했어요
        {me.error instanceof ApiError && <span className="ml-1 font-mono text-xs">({me.error.code})</span>}
      </p>
    )
  }

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-4 p-4">
      <p className="text-sm">지도에 초대받았어요</p>
      <button
        type="button"
        onClick={() => accept.mutate()}
        disabled={accept.isPending}
        className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-50"
      >
        {accept.isPending ? '참여하는 중…' : '참여하기'}
      </button>
      {accept.error && (
        <p className="text-sm text-destructive">
          {/* 목 서버·BE 모두 없는 토큰에 401/404 를 준다. 로그인은 위에서 이미 확인했으니 링크 문제다. */}
          {accept.error instanceof ApiError && ['UNAUTHORIZED', 'NOT_FOUND'].includes(accept.error.code)
            ? '초대 링크가 유효하지 않거나 만료됐어요'
            : '참여하지 못했어요'}
          {accept.error instanceof ApiError && (
            <span className="ml-1 font-mono text-xs">({accept.error.code})</span>
          )}
        </p>
      )}
      <Link to="/" className="text-sm text-muted-foreground">
        내 지도로
      </Link>
    </div>
  )
}
