import { useEffect, useState } from 'react'

import ErrorText from '@/ErrorText'
import ConfirmDialog from '@/ui/ConfirmDialog'
import Pingo from '@/ui/Pingo'
import PingoLoading from '@/ui/PingoLoading'

import { isNoPendingLogin } from './api'
import { formatRestoreUntil, type PendingChoice } from './model'
import { usePendingAccountQuery, usePendingChoiceMutation } from './queries'

/**
 * 탈퇴한 계정으로 다시 로그인했을 때의 선택 화면(#855·#858). 콜백이 세션 없이 `?login_pending=withdrawn_account` 로 돌려보낸다.
 * 고르기 전에는 로그인 상태가 아니다 — 고르면 `onDone`(응답의 User 로 로그인), 고를 게 없어졌으면(404) `onExpired`.
 * 남은 날수와 기한은 응답 값 그대로 쓴다. 「새 계정으로 시작」은 기존 계정을 되살릴 수 없게 지워서 한 번 더 묻는다.
 */
export default function PendingAccountScreen({ onDone, onExpired }: { onDone: () => void; onExpired: () => void }) {
  const pending = usePendingAccountQuery()
  const choose = usePendingChoiceMutation()
  const [confirmRestart, setConfirmRestart] = useState(false)

  const expired = isNoPendingLogin(pending.error) || isNoPendingLogin(choose.error)
  useEffect(() => {
    if (expired) onExpired()
  }, [expired, onExpired])

  const submit = (choice: PendingChoice) => choose.mutate(choice, { onSuccess: onDone })
  // 404 는 화면을 넘기므로 여기서는 그 밖의 실패만 적는다.
  const chooseError = choose.error && !isNoPendingLogin(choose.error) ? choose.error : null

  if (pending.isPending || expired) return <PingoLoading label="계정 정보를 확인하는 중…" className="min-h-dvh justify-center" />
  if (pending.error) {
    return (
      <main className="mx-auto w-full max-w-[480px] space-y-3 px-5 pt-14">
        <ErrorText message="계정 정보를 불러오지 못했어요" error={pending.error} />
        <button type="button" onClick={() => pending.refetch()} className="btn-outline btn-md">
          다시 불러오기
        </button>
      </main>
    )
  }

  const { display_name, days_left, restore_until } = pending.data
  return (
    <div className="min-h-dvh bg-white md:flex md:items-center md:justify-center md:bg-ink-50 md:px-5 md:py-10">
      <main className="mx-auto flex w-full max-w-[480px] flex-col px-5 pb-6 pt-14 md:max-w-[400px] md:rounded-2xl md:border md:border-ink-200 md:bg-white md:px-8 md:py-10">
        <Pingo mood="wave" size={56} />
        <h1 className="mt-4 break-keep text-xl font-bold text-ink-900">이전에 탈퇴한 계정이 있어요</h1>
        <p className="mt-2 break-keep text-sm text-ink-700">
          ‘<span className="font-semibold text-ink-900">{display_name}</span>’ 계정이에요. 새 계정으로 시작하거나,{' '}
          {days_left}일 안에는 기존 계정을 되살릴 수 있어요.
        </p>

        <div className="mt-8 space-y-5">
          <div>
            <button type="button" onClick={() => {
                // 앞서 되살리기가 실패했으면 그 문구를 확인 창에 끌고 들어가지 않는다.
                choose.reset()
                setConfirmRestart(true)
              }} disabled={choose.isPending} className="btn-primary btn-lg w-full">
              새 계정으로 시작
            </button>
            <p className="mt-1.5 break-keep text-xs text-ink-500">기존 계정은 바로 삭제돼요</p>
          </div>
          <div>
            <button type="button" onClick={() => submit('restore')} disabled={choose.isPending} className="btn-outline btn-lg w-full">
              기존 계정 되살리기
            </button>
            <p className="mt-1.5 break-keep text-xs text-ink-500">
              {days_left}일 남음 · {formatRestoreUntil(restore_until)}까지
              <br />
              되살리면 지도 참여가 돌아오고 내가 찍은 핀도 내 이름으로 보여요. 남긴 의견은 돌아오지 않아요
            </p>
          </div>
          {chooseError && !confirmRestart && <ErrorText message="처리하지 못했어요. 다시 시도해 주세요" error={chooseError} />}
        </div>
      </main>

      {confirmRestart && (
        <ConfirmDialog
          title="새 계정으로 시작할까요?"
          body="기존 계정은 바로 삭제되고 되살릴 수 없어요."
          // 320px 의 반 칸 버튼에 들어가게 짧게 — 무엇을 시작하는지는 제목이 말한다.
          ok="새로 시작"
          danger
          pending={choose.isPending}
          onCancel={() => setConfirmRestart(false)}
          onOk={() => submit('restart')}
        >
          {chooseError && <ErrorText message="새 계정을 만들지 못했어요" error={chooseError} />}
        </ConfirmDialog>
      )}
    </div>
  )
}
