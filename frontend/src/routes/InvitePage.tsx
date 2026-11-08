import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { ChevronLeft } from 'lucide-react'

import ErrorText from '@/ErrorText'
import { isUnauthorized } from '@/features/auth/api'
import GoogleButton from '@/features/auth/GoogleButton'
import KakaoButton from '@/features/auth/KakaoButton'
import { clearPendingInvite, savePendingInvite } from '@/features/auth/pendingInvite'
import { DISPLAY_NAME_MAX } from '@/features/auth/model'
import { randomGuestName } from '@/features/auth/guestName'
import { useGuestJoinMutation, useMeQuery } from '@/features/auth/queries'
import { inviteErrorMessage, inviteProblem, type InviteProblem, type InviteView } from '@/features/maps/model'
import { useAcceptInviteMutation, useInviteSummaryQuery } from '@/features/maps/queries'
import EntryFrame from '@/ui/EntryFrame'
import EmptyState from '@/ui/EmptyState'
import { josaRo } from '@/ui/josa'
import PingoLoading from '@/ui/PingoLoading'
import MapIllustration from '@/ui/MapIllustration'
import TextField from '@/ui/TextField'
import Sentences from '@/ui/Sentences'

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

  // 보는 사이 링크가 꺼지면 참여·게스트 입장이 같은 에러로 실패한다 — 그때도 끝 화면으로 바꾼다.
  const [lateProblem, setLateProblem] = useState<InviteProblem | null>(null)
  const problem = inviteProblem(summary.error) ?? lateProblem
  if (problem) return <InviteBroken problem={problem} />

  if (me.isPending || summary.isPending) return <PingoLoading label="초대를 확인하는 중…" className="min-h-dvh justify-center" />

  if (me.error && !needsLogin) {
    return (
      <div className="p-4">
        <ErrorText message="로그인 상태를 확인하지 못했어요" error={me.error} />
      </div>
    )
  }

  // 누구로 참여하는지는 버튼 글이 말한다 — 아래 작은 줄로 두면 안 보였다(#1427).
  const name = me.data?.display_name
  const join = () =>
    // 구성원 온보딩(Figma 2절)은 지도 화면이 이 표시를 보고 띄운다.
    accept.mutate(undefined, {
      onSuccess: (map) => {
        clearPendingInvite()
        navigate(`/maps/${map.id}?onboarding=member`, { replace: true })
      },
      onError: (err) => setLateProblem(inviteProblem(err)),
    })

  return (
    // 넓은 화면은 입구 카드다(#1269).
    <EntryFrame as="div" className="bg-ink-50 px-4 pb-6 pt-4">
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

      <div className="space-y-3 text-center md:mt-6">
        {needsLogin ? (
          <>
            <KakaoButton />
            <GoogleButton />
            <p className="text-xs text-ink-500"><Sentences text="로그인하고 함께 여행 계획을 시작해 보세요" /></p>
            <GuestJoin token={token} onBroken={setLateProblem} />
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
              {accept.isPending ? (
                '참여하는 중…'
              ) : name ? (
                // 버튼 높이가 정해져 있어 긴 이름(최대 50자)은 이름만 「…」로 줄인다.
                <span className="flex min-w-0">
                  <span className="truncate">{name}</span>
                  <span className="shrink-0 whitespace-pre">{`${josaRo(name)} 참여하기`}</span>
                </span>
              ) : (
                '참여하기'
              )}
            </button>
          </>
        )}
      </div>
    </EntryFrame>
  )
}

/**
 * 「로그인 없이 게스트로 들어가기」(#485). 게스트 계정을 만들고 이 초대의 지도에 바로 들어간다(POST /auth/guest).
 * 처음엔 버튼만 두고, 누르면 이름 칸이 열린다 — 카카오가 주 입구라 같은 무게로 펼쳐 두지 않는다.
 * 이름 칸에는 아무 이름(「신나는 수달」)이 미리 들어 있어 바로 들어갈 수 있다. ✕로 지우고 자기 이름을 적어도 된다.
 */
function GuestJoin({ token, onBroken }: { token: string; onBroken: (problem: InviteProblem | null) => void }) {
  const navigate = useNavigate()
  const join = useGuestJoinMutation(token)
  const [open, setOpen] = useState(false)
  const [name, setName] = useState(randomGuestName)
  const trimmed = name.trim()

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className="btn-neutral btn-md w-full">
        로그인 없이 게스트로 들어가기
      </button>
    )
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (!trimmed) return
        join.mutate(trimmed, {
          // 남겨 둔 초대를 여기서 지운다. 화면이 바로 넘어가 「로그인됨」 효과가 돌기 전에 사라지면,
          // 나중에 내 지도 목록이 이 초대로 다시 보낸다.
          onSuccess: ({ map }) => {
            clearPendingInvite()
            navigate(`/maps/${map.id}?onboarding=member`, { replace: true })
          },
          onError: (err) => onBroken(inviteProblem(err)),
        })
      }}
      className="space-y-2 rounded-xl border border-ink-200 bg-white p-3 text-left"
    >
      <label htmlFor="guest-name" className="block text-sm font-semibold text-ink-900">
        구성원에게 보일 이름
      </label>
      <TextField id="guest-name" value={name} onChange={setName} maxLength={DISPLAY_NAME_MAX} placeholder="예: 지우" clearLabel="이름 지우기" autoFocus />
      <p className="break-keep text-xs text-ink-500">
        <Sentences text="자동으로 지은 이름이에요. 원하면 바꿔도 돼요" />
      </p>
      <p className="break-keep text-xs text-ink-500">
        <Sentences text="게스트는 새 지도를 만들 수 없어요. 나중에 카카오로 가입하면 기록이 그대로 이어져요" />
      </p>
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
      {/* 넓은 화면은 바깥이 이미 카드라 테두리를 빼 카드 안 카드가 되지 않게 한다. */}
      <div className="rounded-xl border border-ink-200 bg-white p-4 text-center md:border-0 md:p-0">
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
const BROKEN_TITLE: Record<InviteProblem, string> = {
  expired: '초대 링크가 만료됐어요',
  revoked: '방장이 이 초대 링크를 껐어요',
  invalid: '잘못된 초대 링크예요',
}

/** 더 쓸 수 없는 초대 링크(#719). 참여 버튼과 에러 코드를 보이지 않는다 — 다음 행동은 새 링크 받기와 내 지도로. */
function InviteBroken({ problem }: { problem: InviteProblem }) {
  return (
    <EntryFrame as="div" className="bg-ink-50 px-4 pb-6">
      <div className="flex flex-1 flex-col justify-center">
        <EmptyState mood="sad" title={BROKEN_TITLE[problem]}>
          초대한 친구에게 새 링크를 받아주세요
        </EmptyState>
      </div>
      <Link to="/" className="btn-primary btn-lg md:mt-6">
        내 지도로
      </Link>
    </EntryFrame>
  )
}
