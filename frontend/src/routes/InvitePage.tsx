import { useEffect } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { ChevronLeft, Link2Off } from 'lucide-react'

import ErrorText from '@/ErrorText'
import { isUnauthorized } from '@/features/auth/api'
import KakaoButton from '@/features/auth/KakaoButton'
import { clearPendingInvite, savePendingInvite } from '@/features/auth/pendingInvite'
import { useMeQuery } from '@/features/auth/queries'
import { inviteErrorMessage, inviteProblem, type InviteView } from '@/features/maps/model'
import { useAcceptInviteMutation, useInviteSummaryQuery } from '@/features/maps/queries'
import MapIllustration from '@/ui/MapIllustration'

/**
 * 초대 수락 (#4, Figma 2절). 로그인 전(C-1)·로그인 후 구성원 아님(C-2)·만료(C-3).
 * 로그인 전엔 토큰을 들고 로그인으로 보내고, 로그인 후 목록에서 여기로 되돌아온다.
 */
export default function InvitePage() {
  const { token = '' } = useParams()
  const navigate = useNavigate()
  const me = useMeQuery()
  const summary = useInviteSummaryQuery(token)
  const accept = useAcceptInviteMutation(token)
  const loggedIn = Boolean(me.data)
  const needsLogin = isUnauthorized(me.error)

  useEffect(() => {
    if (needsLogin) savePendingInvite(token)
    if (loggedIn) clearPendingInvite()
  }, [needsLogin, loggedIn, token])

  const problem = inviteProblem(summary.error)
  if (problem) return <InviteBroken expired={problem === 'expired'} />

  if (me.isPending || summary.isPending) return <p className="p-4 text-sm text-ink-500">확인하는 중…</p>

  if (me.error && !needsLogin) {
    return (
      <div className="p-4">
        <ErrorText message="로그인 상태를 확인하지 못했어요" error={me.error} />
      </div>
    )
  }

  const join = () =>
    // 구성원 온보딩(Figma 2절)은 지도 화면이 이 표시를 보고 띄운다.
    accept.mutate(undefined, { onSuccess: (map) => navigate(`/maps/${map.id}?onboarding=member`, { replace: true }) })

  return (
    <div className="flex min-h-dvh flex-col bg-ink-50 px-4 pb-6 pt-4">
      <div className="h-8">
        {loggedIn && (
          <Link to="/" aria-label="내 지도 목록으로" className="flex size-8 items-center justify-center rounded-full bg-white shadow-sm">
            <ChevronLeft size={20} />
          </Link>
        )}
      </div>

      <div className="flex flex-1 flex-col justify-center">
        {summary.data ? (
          <InviteCard invite={summary.data} />
        ) : (
          <ErrorText message="초대 정보를 불러오지 못했어요" error={summary.error} />
        )}
      </div>

      <div className="space-y-3 text-center">
        {needsLogin ? (
          <>
            <KakaoButton />
            <p className="text-xs text-ink-500">로그인하면 바로 이 지도에 참여해요</p>
          </>
        ) : (
          <>
            {accept.error && <ErrorText message={inviteErrorMessage(accept.error)} error={accept.error} />}
            <button
              type="button"
              onClick={join}
              disabled={accept.isPending}
              className="w-full rounded-xl bg-brand-600 py-3.5 font-semibold text-white disabled:opacity-50"
            >
              {accept.isPending ? '참여하는 중…' : '참여하기'}
            </button>
            <p className="text-xs text-ink-500">{me.data?.display_name} (나)로 참여해요</p>
          </>
        )}
      </div>
    </div>
  )
}

function InviteCard({ invite }: { invite: InviteView }) {
  return (
    <>
      <p className="mb-3 text-center text-sm text-ink-500">{invite.inviter}님이 초대했어요</p>
      <div className="rounded-2xl border border-ink-200 bg-white p-4 text-center">
        <MapIllustration />
        <h1 className="mt-4 text-2xl font-bold text-ink-900">{invite.title}</h1>
        <p className="mt-1 text-sm text-ink-500">{invite.dates}</p>
        <p className="mt-1 text-xs text-ink-500">
          구성원 {invite.memberCount}명 · 핀 {invite.pinCount}개
        </p>
      </div>
    </>
  )
}

/** C-3 — 만료됐거나 없는 링크. 초대한 사람에게 새 링크를 받는 것 말고는 할 수 있는 게 없다. */
function InviteBroken({ expired }: { expired: boolean }) {
  return (
    <div className="flex min-h-dvh flex-col bg-ink-50 px-4 pb-6">
      <div className="flex flex-1 flex-col items-center justify-center text-center">
        <span className="mb-3 flex size-16 items-center justify-center rounded-2xl bg-ink-100 text-ink-500">
          <Link2Off size={28} aria-hidden="true" />
        </span>
        <p className="font-semibold text-ink-900">{expired ? '초대 링크가 만료됐어요' : '유효하지 않은 초대 링크예요'}</p>
        <p className="mt-1 text-sm text-ink-500">초대한 친구에게 새 링크를 받아주세요</p>
      </div>
      <Link to="/" className="rounded-xl bg-brand-600 py-3.5 text-center font-semibold text-white">
        내 지도로
      </Link>
    </div>
  )
}
