import { useState } from 'react'

import ErrorText from '@/ErrorText'
import { showToast } from '@/features/shell/toast'

import { useInvitesQuery, useRevokeInviteMutation } from './queries'

/**
 * 켜진 초대 링크 관리(방장, #467). 펼쳤을 때만 목록을 받는다. 끈 링크로는 더 들어올 수 없고, 이미 들어온 사람은 그대로다.
 * 끄기는 확인 창 없이 바로 한다 — 새 링크는 언제든 다시 만들 수 있다.
 */
export default function InviteLinks({ mapId, onRevoked }: { mapId: string; onRevoked: (token: string) => void }) {
  const [open, setOpen] = useState(false)
  const invites = useInvitesQuery(mapId, open)
  const revoke = useRevokeInviteMutation(mapId)

  return (
    <div className="mt-1">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="btn-link text-sm">
        {open ? '켜진 초대 링크 접기' : '켜진 초대 링크 관리'}
      </button>
      {open && (
        <div className="mt-1 space-y-2">
          {invites.error && <ErrorText message="초대 링크 목록을 불러오지 못했어요" error={invites.error} />}
          {invites.data?.length === 0 && <p className="text-xs text-ink-500">켜진 초대 링크가 없어요</p>}
          <ul className="space-y-2">
            {invites.data?.map((invite) => (
              <li key={invite.token} className="flex items-center justify-between gap-2 rounded-xl bg-ink-50 px-3 py-2.5">
                <span className="min-w-0 text-xs text-ink-600">{invite.label}</span>
                <button
                  type="button"
                  disabled={revoke.isPending && revoke.variables === invite.token}
                  onClick={() =>
                    revoke.mutate(invite.token, {
                      onSuccess: () => {
                        showToast('초대 링크를 껐어요. 이 링크로는 더 들어올 수 없어요')
                        onRevoked(invite.token)
                      },
                      onError: () => showToast('초대 링크를 끄지 못했어요'),
                    })
                  }
                  className="btn-outline btn-sm shrink-0"
                >
                  끄기
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
