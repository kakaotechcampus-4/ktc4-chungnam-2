import { useState } from 'react'
import { Share } from 'lucide-react'

import ErrorText from '@/ErrorText'
import LogoutConfirm from '@/features/auth/LogoutConfirm'
import { useMeQuery } from '@/features/auth/queries'
import ModalSheet from '@/features/shell/ModalSheet'
import { showToast } from '@/features/shell/toast'

import type { MapView } from './model'
import { useCreateInviteMutation } from './queries'

/**
 * 내 지도 목록의 계정 시트(Figma 1절). 지도마다 초대 링크가 따로라 줄마다 복사 버튼을 둔다.
 * 회원 탈퇴는 확인 창 디자인이 아직 없어 넣지 않았다.
 */
export default function AccountSheet({ maps, onClose }: { maps: MapView[]; onClose: () => void }) {
  const me = useMeQuery().data
  const invite = useCreateInviteMutation()
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [confirmLogout, setConfirmLogout] = useState(false)

  function copyLink(map: MapView) {
    invite.mutate(map.id, {
      onSuccess: async ({ url }) => {
        try {
          await navigator.clipboard.writeText(url)
          setCopiedId(map.id)
          showToast(`${map.title} 초대 링크를 복사했어요`)
        } catch (err) {
          console.error('[account] 링크 복사 실패', err)
          showToast('링크를 복사하지 못했어요. 지도 안 프로필에서 공유해 주세요')
        }
      },
    })
  }

  return (
    <ModalSheet
      label="계정"
      onClose={onClose}
      overlay={confirmLogout && <LogoutConfirm onCancel={() => setConfirmLogout(false)} />}
    >
      <div className="mb-5 flex items-center gap-3">
        <span className="flex size-11 items-center justify-center rounded-full bg-brand-600 text-lg font-bold text-white">
          {me?.display_name?.slice(0, 1)}
        </span>
        <div>
          <p className="text-lg font-bold text-ink-900">{me?.display_name}</p>
          <p className="text-xs text-ink-500">카카오로 로그인됨 · 지도 {maps.length}개</p>
        </div>
      </div>

      {maps.length > 0 && (
        <>
          <h2 className="font-semibold text-ink-900">지도 초대 링크</h2>
          <p className="mb-2 text-xs text-ink-500">지도마다 링크가 따로 있어요. 복사해서 단톡방에 보내 주세요</p>
          <ul className="space-y-2">
            {maps.map((map) => (
              <li key={map.id} className="flex items-center justify-between gap-2 rounded-lg bg-ink-50 px-3 py-2.5">
                <span className="truncate text-sm text-ink-900">{map.title}</span>
                <button
                  type="button"
                  onClick={() => copyLink(map)}
                  disabled={invite.isPending && invite.variables === map.id}
                  className="flex shrink-0 items-center gap-1 rounded-lg border border-brand-600 px-2.5 py-1 text-xs font-semibold text-brand-600"
                >
                  {copiedId === map.id ? '✓ 복사됨' : <><Share size={12} aria-hidden="true" /> 링크 복사</>}
                </button>
              </li>
            ))}
          </ul>
          {invite.error && <ErrorText message="초대 링크를 만들지 못했어요" error={invite.error} />}
        </>
      )}

      <button
        type="button"
        onClick={() => setConfirmLogout(true)}
        className="mt-5 w-full rounded-xl border border-ink-300 py-3 font-semibold text-ink-900"
      >
        로그아웃
      </button>
    </ModalSheet>
  )
}
