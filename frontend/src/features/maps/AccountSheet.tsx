import { useState } from 'react'
import { Popover } from 'radix-ui'
import { Share } from 'lucide-react'

import ErrorText from '@/ErrorText'
import LogoutConfirm from '@/features/auth/LogoutConfirm'
import WithdrawConfirm from '@/features/auth/WithdrawConfirm'
import { useMeQuery } from '@/features/auth/queries'
import ModalSheet from '@/features/shell/ModalSheet'
import { showToast } from '@/features/shell/toast'

import { MAP_LIMIT, type MapView } from './model'
import { useCreateInviteMutation } from './queries'

type Confirm = 'logout' | 'withdraw' | null

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

/**
 * 넓은 화면의 계정 메뉴 — 화면 바닥 시트 대신 계정 버튼 바로 아래에 붙는다.
 * 확인 창이 떠 있는 동안은 메뉴를 닫지 않는다(모바일 시트 위에 확인 창이 뜨는 것과 같게). 취소하면 메뉴로 돌아온다.
 */
export function AccountMenu({ maps, initial }: { maps: MapView[]; initial?: string }) {
  const [confirm, setConfirm] = useState<Confirm>(null)
  const keepOpen = (e: Event) => {
    if (confirm) e.preventDefault()
  }
  return (
    <Popover.Root>
      <Popover.Trigger
        aria-label="계정"
        className="hit-44 flex size-9 items-center justify-center rounded-full bg-brand-600 text-sm font-semibold text-white outline-offset-2 focus-visible:outline-2 focus-visible:outline-[var(--line-focus)]"
      >
        {initial}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          aria-label="계정"
          align="end"
          sideOffset={8}
          collisionPadding={16}
          onInteractOutside={keepOpen}
          onFocusOutside={keepOpen}
          className="z-50 max-h-[var(--radix-popover-content-available-height)] w-[22rem] overflow-y-auto rounded-2xl border border-ink-200 bg-white p-4 shadow-md outline-none"
        >
          <AccountBody maps={maps} onConfirm={setConfirm} />
        </Popover.Content>
      </Popover.Portal>
      <AccountConfirm which={confirm} onCancel={() => setConfirm(null)} />
    </Popover.Root>
  )
}

function AccountConfirm({ which, onCancel }: { which: Confirm; onCancel: () => void }) {
  if (which === 'logout') return <LogoutConfirm onCancel={onCancel} />
  if (which === 'withdraw') return <WithdrawConfirm onCancel={onCancel} />
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
        <span className="flex size-11 items-center justify-center rounded-full bg-brand-600 text-lg font-bold text-white">
          {me?.display_name?.slice(0, 1)}
        </span>
        <div>
          <p className="text-lg font-bold text-ink-900">{me?.display_name}</p>
          <p className="text-xs text-ink-500">카카오로 로그인됨 · 지도 {maps.length}/{MAP_LIMIT}개</p>
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
                  className="btn-outline hit-44 flex shrink-0 items-center gap-1 rounded-md px-2.5 py-1 text-xs"
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
        onClick={() => onConfirm('logout')}
        className="mt-5 w-full rounded-xl border border-ink-300 py-3 font-semibold text-ink-900"
      >
        로그아웃
      </button>
      <button type="button" onClick={() => onConfirm('withdraw')} className="hit-44 mt-2 w-full text-center text-xs text-ink-500 underline">
        회원 탈퇴
      </button>
    </>
  )
}
