import { useEffect } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import ErrorText from '@/ErrorText'
import { isUnauthorized } from '@/features/auth/api'
import { clearPendingInvite, savePendingInvite } from '@/features/auth/pendingInvite'
import { useMeQuery } from '@/features/auth/queries'
import { LoginScreen } from '@/features/auth/RequireLogin'
import { inviteErrorMessage } from '@/features/maps/model'
import { useAcceptInviteMutation } from '@/features/maps/queries'

/**
 * 초대 수락 (#4). 비로그인이면 토큰을 들고 로그인으로 보내고, 로그인 후 목록에서 여기로 되돌아온다.
 *
 * 로그인 전 "읽기만"(#23)은 아직 못 한다 — 토큰으로 지도를 미리 볼 수 있는 API 가 스펙에 없다.
 * 지금은 로그인 안내만 띄운다.
 */
export default function InvitePage() {
  const { token = '' } = useParams()
  const navigate = useNavigate()
  const me = useMeQuery()
  const loggedIn = Boolean(me.data)
  const needsLogin = isUnauthorized(me.error)

  useEffect(() => {
    if (needsLogin) savePendingInvite(token)
    if (loggedIn) clearPendingInvite()
  }, [needsLogin, loggedIn, token])

  const accept = useAcceptInviteMutation(token)
  const join = () =>
    accept.mutate(undefined, { onSuccess: (map) => navigate(`/maps/${map.id}`, { replace: true }) })

  if (me.isPending) return <p className="p-4 text-sm text-muted-foreground">확인하는 중…</p>

  if (needsLogin) {
    return <LoginScreen message="지도에 초대받았어요. 로그인하고 참여하세요" />
  }

  if (me.error) {
    return (
      <div className="p-4">
        <ErrorText message="로그인 상태를 확인하지 못했어요" error={me.error} />
      </div>
    )
  }

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-4 p-4">
      <p className="text-sm">지도에 초대받았어요</p>
      <button
        type="button"
        onClick={join}
        disabled={accept.isPending}
        className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-50"
      >
        {accept.isPending ? '참여하는 중…' : '참여하기'}
      </button>
      {accept.error && (
        <ErrorText message={inviteErrorMessage(accept.error)} error={accept.error} />
      )}
      <Link to="/" className="text-sm text-muted-foreground">
        내 지도로
      </Link>
    </div>
  )
}
