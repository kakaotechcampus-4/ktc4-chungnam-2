import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { ChevronLeft } from 'lucide-react'

import ErrorText from '@/ErrorText'
import { isUnauthorized } from '@/features/auth/api'
import KakaoButton from '@/features/auth/KakaoButton'
import { clearPendingInvite, savePendingInvite } from '@/features/auth/pendingInvite'
import { DISPLAY_NAME_MAX } from '@/features/auth/model'
import { useGuestJoinMutation, useMeQuery } from '@/features/auth/queries'
import { inviteErrorMessage, inviteProblem, type InviteView } from '@/features/maps/model'
import { useAcceptInviteMutation, useInviteSummaryQuery } from '@/features/maps/queries'
import EmptyState from '@/ui/EmptyState'
import PingoLoading from '@/ui/PingoLoading'
import MapIllustration from '@/ui/MapIllustration'
import TextField from '@/ui/TextField'

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

  if (me.isPending || summary.isPending) return <PingoLoading label="초대를 확인하는 중…" className="min-h-dvh justify-center" />

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
    <div className="mx-auto flex min-h-dvh w-full max-w-[480px] flex-col bg-ink-50 px-4 pb-6 pt-4">
      <div className="h-8">
        {loggedIn && (
          <Link to="/" aria-label="내 지도 목록으로" className="hit-44 flex size-8 items-center justify-center rounded-full bg-white shadow-float">
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
            <GuestJoin token={token} />
          </>
        ) : (
          <>
            {accept.error && <ErrorText message={inviteErrorMessage(accept.error)} error={accept.error} />}
            <button
              type="button"
              onClick={join}
              disabled={accept.isPending}
              className="btn-primary btn-lg w-full"
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

/**
 * 「이름만 입력하고 들어가기」(#485). 게스트 계정을 만들고 이 초대의 지도에 바로 들어간다(POST /auth/guest).
 * 처음엔 버튼만 두고, 누르면 이름 칸이 열린다 — 카카오가 주 입구라 같은 무게로 펼쳐 두지 않는다.
 */
function GuestJoin({ token }: { token: string }) {
  const navigate = useNavigate()
  const join = useGuestJoinMutation(token)
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const trimmed = name.trim()

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className="btn-neutral btn-md w-full">
        이름만 입력하고 들어가기
      </button>
    )
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (!trimmed) return
        join.mutate(trimmed, { onSuccess: ({ map }) => navigate(`/maps/${map.id}?onboarding=member`, { replace: true }) })
      }}
      className="space-y-2 rounded-xl border border-ink-200 bg-white p-3 text-left"
    >
      <label htmlFor="guest-name" className="block text-sm font-semibold text-ink-900">
        구성원에게 보일 이름
      </label>
      <TextField id="guest-name" value={name} onChange={setName} maxLength={DISPLAY_NAME_MAX} placeholder="예: 지우" clearLabel="이름 지우기" autoFocus />
      <p className="break-keep text-xs text-ink-500">게스트는 새 지도를 만들 수 없어요. 나중에 카카오로 계정을 만들면 기록이 이어져요</p>
      {join.error && <ErrorText message={inviteErrorMessage(join.error)} error={join.error} />}
      <button type="submit" disabled={!trimmed || join.isPending} className="btn-primary btn-md w-full">
        {join.isPending ? '들어가는 중…' : '게스트로 참여하기'}
      </button>
    </form>
  )
}

function InviteCard({ invite }: { invite: InviteView }) {
  return (
    <>
      <p className="mb-3 text-center text-sm text-ink-500">{invite.inviter}님이 초대했어요</p>
      <div className="rounded-xl border border-ink-200 bg-white p-4 text-center">
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
    <div className="mx-auto flex min-h-dvh w-full max-w-[480px] flex-col bg-ink-50 px-4 pb-6">
      <div className="flex flex-1 flex-col justify-center">
        <EmptyState mood="sorry" title={expired ? '초대 링크가 만료됐어요' : '유효하지 않은 초대 링크예요'}>
          초대한 친구에게 새 링크를 받아주세요
        </EmptyState>
      </div>
      <Link to="/" className="btn-primary btn-lg">
        내 지도로
      </Link>
    </div>
  )
}
