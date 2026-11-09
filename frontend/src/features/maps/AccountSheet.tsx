import { useState, type ReactNode } from 'react'
import { Share } from 'lucide-react'

import ErrorText from '@/ErrorText'
import EditNameDialog from '@/features/auth/EditNameDialog'
import GuestAccountNotice from '@/features/auth/GuestAccountNotice'
import LogoutConfirm from '@/features/auth/LogoutConfirm'
import WithdrawConfirm from '@/features/auth/WithdrawConfirm'
import { useMeQuery } from '@/features/auth/queries'
import FeedbackSheet from '@/features/feedback/FeedbackSheet'
import FaqSheet from '@/features/help/FaqSheet'
import MenuPopover from '@/features/shell/MenuPopover'
import ModalSheet from '@/features/shell/ModalSheet'
import { HelpLinks } from '@/features/shell/ProfileModal'
import ThemeControl from '@/features/shell/ThemeControl'
import { showToast } from '@/features/shell/toast'
import Avatar from '@/ui/Avatar'
import Sentences from '@/ui/Sentences'
import SheetTitle from '@/ui/SheetTitle'

import type { MapView } from './model'
import { useCreateInviteMutation } from './queries'

type Confirm = 'logout' | 'withdraw' | 'name' | 'feedback' | 'bug' | 'faq' | null

/**
 * 내 지도 목록의 계정 시트(Figma 1절, 모바일). 넓은 화면은 같은 내용을 계정 버튼 아래 메뉴로 연다(AccountMenu).
 * 회원 탈퇴는 로그아웃 아래 글자 버튼으로 둔다(#155) — 눈에 잘 띄는 자리에 두지 않는다.
 */
export default function AccountSheet({ maps, onClose }: { maps: MapView[]; onClose: () => void }) {
  const [confirm, setConfirm] = useState<Confirm>(null)
  return (
    <ModalSheet label="계정" onClose={onClose} overlay={<AccountConfirm which={confirm} onCancel={() => setConfirm(null)} />}>
      <AccountBody maps={maps} onConfirm={setConfirm} />
      <AccountSettings onConfirm={setConfirm} />
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
      <AccountSettings onConfirm={setConfirm} />
    </MenuPopover>
  )
}

/**
 * 지도 화면 프로필 탭(휴대폰)의 계정 칸. 시트, 메뉴 없이 탭 시트 안에 그대로 놓는다.
 * `links`는 이름 줄 바로 아래 바로 가기 자리, `mapId`는 의견 보내기에 지금 지도를 붙인다.
 * 화면 모드, 도움 줄, 로그아웃, 회원 탈퇴는 탭 머리의 톱니 버튼이 여는 설정 시트(`settingsOpen`)에 있다.
 */
export function AccountSection({
  maps,
  mapId,
  links,
  settingsOpen,
  onSettingsClose,
}: {
  maps: MapView[]
  mapId?: string
  links?: ReactNode
  settingsOpen: boolean
  onSettingsClose: () => void
}) {
  const [confirm, setConfirm] = useState<Confirm>(null)
  const overlay = <AccountConfirm which={confirm} mapId={mapId} onCancel={() => setConfirm(null)} />
  return (
    <>
      <AccountBody maps={maps} onConfirm={setConfirm} links={links} />
      {settingsOpen ? (
        <ModalSheet label="설정" onClose={onSettingsClose} overlay={overlay}>
          <SheetTitle>설정</SheetTitle>
          <AccountSettings onConfirm={setConfirm} />
        </ModalSheet>
      ) : (
        overlay
      )}
    </>
  )
}

function AccountConfirm({ which, mapId, onCancel }: { which: Confirm; mapId?: string; onCancel: () => void }) {
  if (which === 'logout') return <LogoutConfirm onCancel={onCancel} />
  if (which === 'withdraw') return <WithdrawConfirm onCancel={onCancel} />
  if (which === 'name') return <EditNameDialog onCancel={onCancel} />
  if (which === 'feedback') return <FeedbackSheet mapId={mapId} onClose={onCancel} />
  if (which === 'bug') return <FeedbackSheet mapId={mapId} initialCategory="bug" onClose={onCancel} />
  if (which === 'faq') return <FaqSheet onClose={onCancel} />
  return null
}

/** 계정 시트·메뉴 공통 내용. 지도마다 초대 링크가 따로라 줄마다 복사 버튼을 둔다. */
function AccountBody({ maps, onConfirm, links }: { maps: MapView[]; onConfirm: (which: Confirm) => void; links?: ReactNode }) {
  const me = useMeQuery().data
  const invite = useCreateInviteMutation()
  const [copiedId, setCopiedId] = useState<string | null>(null)

  function copyLink(map: MapView) {
    if (invite.isPending) return
    let linkFailed = false
    const url = invite.mutateAsync(map.id).then(
      (r) => r.url,
      (err: unknown) => {
        linkFailed = true
        throw err
      },
    )
    // 클립보드 쓰기가 먼저 거절되면 아래 Blob 약속을 아무도 받지 않는다 — 처리되지 않은 거절로 남지 않게.
    url.catch(() => {})
    // Safari 는 누른 그 순간에 클립보드에 쓰기 시작해야 한다 — 링크를 받은 뒤 쓰면 늘 거절했다.
    // 그래서 아직 오지 않은 링크(Promise)를 담은 ClipboardItem 을 바로 넘긴다. 없는 브라우저는 받은 뒤 글자로 쓴다.
    const copied =
      typeof ClipboardItem !== 'undefined' && navigator.clipboard?.write
        ? navigator.clipboard.write([new ClipboardItem({ 'text/plain': url.then((u) => new Blob([u], { type: 'text/plain' })) })])
        : url.then((u) => navigator.clipboard.writeText(u))
    copied.then(
      () => {
        setCopiedId(map.id)
        showToast(`${map.title} 초대 링크를 복사했어요`)
      },
      (err) => {
        // 링크를 못 만든 것은 아래 오류 줄이 알린다.
        if (linkFailed) return
        console.error('[account] 링크 복사 실패', err)
        showToast('링크를 복사하지 못했어요. 지도에 들어가 지도 정보에서 공유해 보세요')
      },
    )
  }

  return (
    <>
      <div className="mb-5 flex items-center gap-3">
        <Avatar name={me?.display_name} size={44} />
        <div className="min-w-0 flex-1">
          <p className="text-xl font-bold text-ink-900">{me?.display_name}</p>
          <p className="text-xs text-ink-500">
            {me?.is_guest ? <span className="tag tag-neutral mr-1">게스트</span> : '로그인됨 · '}
            지도 {maps.length}개
          </p>
        </div>
        <button type="button" onClick={() => onConfirm('name')} className="btn-link shrink-0">
          이름 바꾸기
        </button>
      </div>
      {links}
      {me?.is_guest && <div className="mb-5 mt-1"><GuestAccountNotice /></div>}

      {maps.length > 0 && (
        <>
          <h2 className="text-sm font-bold text-ink-900">지도 초대 링크</h2>
          <p className="mb-2 text-xs text-ink-500">
            <Sentences text="지도마다 링크가 따로 있어요. 복사해서 단톡방에 보내 주세요" />
          </p>
          <ul className="space-y-2">
            {maps.map((map) => (
              <li key={map.id} className="flex items-center justify-between gap-2 rounded-xl bg-ink-50 px-3 py-2.5">
                <span className="truncate text-sm text-ink-900">{map.title}</span>
                <button
                  type="button"
                  onClick={() => copyLink(map)}
                  // 한 요청을 여러 줄이 같이 쓰니, 기다리는 동안은 모든 줄을 막는다(앞 줄의 결과가 사라지지 않게).
                  disabled={invite.isPending}
                  className="btn-outline btn-sm"
                >
                  {copiedId === map.id ? '복사됨' : <><Share size={14} aria-hidden="true" /> 링크 복사</>}
                </button>
              </li>
            ))}
          </ul>
          {invite.error && <ErrorText message="초대 링크를 만들지 못했어요" error={invite.error} />}
        </>
      )}

    </>
  )
}

/** 계정 시트, 메뉴의 아래쪽(화면 모드, 도움 줄, 로그아웃, 회원 탈퇴). 프로필 탭에서는 설정 시트로 따로 연다. */
function AccountSettings({ onConfirm }: { onConfirm: (which: Confirm) => void }) {
  return (
    <>
      {/* 내 지도 목록에는 ☰ 메뉴가 없어서 화면 모드를 계정에 둔다(#1412). */}
      <ThemeControl className="mt-5" />
      <div className="mt-2">
        <HelpLinks onPick={onConfirm} />
      </div>
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
