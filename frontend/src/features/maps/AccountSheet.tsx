import { useState } from 'react'
import { Share } from 'lucide-react'

import ErrorText from '@/ErrorText'
import EditNameDialog from '@/features/auth/EditNameDialog'
import GuestAccountNotice from '@/features/auth/GuestAccountNotice'
import LogoutConfirm from '@/features/auth/LogoutConfirm'
import WithdrawConfirm from '@/features/auth/WithdrawConfirm'
import { useMeQuery } from '@/features/auth/queries'
import FeedbackSheet from '@/features/feedback/FeedbackSheet'
import MenuPopover from '@/features/shell/MenuPopover'
import ModalSheet from '@/features/shell/ModalSheet'
import { showToast } from '@/features/shell/toast'
import Avatar from '@/ui/Avatar'

import type { MapView } from './model'
import { useCreateInviteMutation } from './queries'

type Confirm = 'logout' | 'withdraw' | 'name' | 'feedback' | null

/**
 * 내 지도 목록의 계정 시트(Figma 1절, 모바일). 넓은 화면은 같은 내용을 계정 버튼 아래 메뉴로 연다(AccountMenu).
 * 회원 탈퇴는 로그아웃 아래 글자 버튼으로 둔다(#155) — 눈에 잘 띄는 자리에 두지 않는다.
 */
export default function AccountSheet({ maps, onClose }: { maps: MapView[]; onClose: () => void }) {
  const [confirm, setConfirm] = useState<Confirm>(null)
  return (
    <ModalSheet label="계정" onClose={onClose} overlay={<AccountConfirm which={confirm} onCancel={() => setConfirm(null)} />}>
      <AccountBody maps={maps} onConfirm={setConfirm} />
    </ModalSheet>
  )
}

/** 넓은 화면의 계정 메뉴 — 화면 바닥 시트 대신 계정 버튼 바로 아래에 붙는다. */
export function AccountMenu({ maps, name }: { maps: MapView[]; name?: string }) {
  const [confirm, setConfirm] = useState<Confirm>(null)
  return (
    <MenuPopover
      label="계정"
      holdOpen={confirm !== null}
      overlay={<AccountConfirm which={confirm} onCancel={() => setConfirm(null)} />}
      trigger={
        <button
          type="button"
          aria-label="계정"
          className="hit-44 rounded-full outline-offset-2 focus-visible:outline-2 focus-visible:outline-[var(--line-focus)]"
        >
          <Avatar name={name} />
        </button>
      }
    >
      <AccountBody maps={maps} onConfirm={setConfirm} />
    </MenuPopover>
  )
}

function AccountConfirm({ which, onCancel }: { which: Confirm; onCancel: () => void }) {
  if (which === 'logout') return <LogoutConfirm onCancel={onCancel} />
  if (which === 'withdraw') return <WithdrawConfirm onCancel={onCancel} />
  if (which === 'name') return <EditNameDialog onCancel={onCancel} />
  if (which === 'feedback') return <FeedbackSheet onClose={onCancel} />
  return null
}

/** 계정 시트·메뉴 공통 내용. 지도마다 초대 링크가 따로라 줄마다 복사 버튼을 둔다. */
function AccountBody({ maps, onConfirm }: { maps: MapView[]; onConfirm: (which: Confirm) => void }) {
  const me = useMeQuery().data
  const invite = useCreateInviteMutation()
  const [copiedId, setCopiedId] = useState<string | null>(null)

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
    <>
      <div className="mb-5 flex items-center gap-3">
        <Avatar name={me?.display_name} size={44} />
        <div className="min-w-0 flex-1">
          <p className="text-xl font-bold text-ink-900">{me?.display_name}</p>
          <p className="text-xs text-ink-500">
            {me?.is_guest ? <span className="tag tag-neutral mr-1">게스트</span> : '카카오로 로그인됨 · '}
            지도 {maps.length}개
          </p>
        </div>
        <button type="button" onClick={() => onConfirm('name')} className="btn-link shrink-0">
          이름 바꾸기
        </button>
      </div>
      {me?.is_guest && <div className="-mt-2 mb-5"><GuestAccountNotice /></div>}

      {maps.length > 0 && (
        <>
          <h2 className="text-sm font-bold text-ink-900">지도 초대 링크</h2>
          <p className="mb-2 text-xs text-ink-500">지도마다 링크가 따로 있어요. 복사해서 단톡방에 보내 주세요</p>
          <ul className="space-y-2">
            {maps.map((map) => (
              <li key={map.id} className="flex items-center justify-between gap-2 rounded-xl bg-ink-50 px-3 py-2.5">
                <span className="truncate text-sm text-ink-900">{map.title}</span>
                <button
                  type="button"
                  onClick={() => copyLink(map)}
                  disabled={invite.isPending && invite.variables === map.id}
                  className="btn-outline btn-sm"
                >
                  {copiedId === map.id ? '✓ 복사됨' : <><Share size={14} aria-hidden="true" /> 링크 복사</>}
                </button>
              </li>
            ))}
          </ul>
          {invite.error && <ErrorText message="초대 링크를 만들지 못했어요" error={invite.error} />}
        </>
      )}

      <button type="button" onClick={() => onConfirm('feedback')} className="btn-text mt-5 w-full text-center text-body">
        핑고핑고에 의견 보내기
      </button>
      <button
        type="button"
        onClick={() => onConfirm('logout')}
        className="btn-neutral btn-md mt-2 w-full"
      >
        로그아웃
      </button>
      <button type="button" onClick={() => onConfirm('withdraw')} className="btn-text mt-2 w-full text-center text-xs underline">
        회원 탈퇴
      </button>
    </>
  )
}
