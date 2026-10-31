import { useState, type ReactNode } from 'react'
import { Share } from 'lucide-react'

import ErrorText from '@/ErrorText'
import GuestAccountNotice from '@/features/auth/GuestAccountNotice'
import LogoutConfirm from '@/features/auth/LogoutConfirm'
import { useMeQuery } from '@/features/auth/queries'
import { useMapQuery, useMembersQuery } from '@/features/maps/queries'
import { DeleteMapConfirm, LeaveMapConfirm } from '@/features/maps/MapLifecycle'
import { useShareInvite } from '@/features/maps/useShareInvite'
import Avatar from '@/ui/Avatar'

import MenuPopover from './MenuPopover'
import ModalSheet from './ModalSheet'

type Confirm = 'logout' | 'leave' | 'delete' | null

/**
 * 프로필 모달(Figma 8절, 모바일). 탭 시트가 아니라 모달이다 — 탭 시트 자리에 띄우면 켜진 탭과 내용이 어긋난다.
 * 검정 32% 딤이 지도·상단 버튼·하단 바까지 덮고, 시트는 화면 바닥에 붙는다.
 * 넓은 화면은 같은 내용을 패널 헤더 구성원 버튼 아래 메뉴로 연다(ProfileMenu). 강퇴는 v2라 버튼이 없다.
 */
export default function ProfileModal({ mapId, onClose }: { mapId: string; onClose: () => void }) {
  const [confirm, setConfirm] = useState<Confirm>(null)
  return (
    <ModalSheet label="지도 정보" fullWidth onClose={onClose} overlay={<ProfileConfirm mapId={mapId} which={confirm} onCancel={() => setConfirm(null)} />}>
      <ProfileBody mapId={mapId} onConfirm={setConfirm} />
    </ModalSheet>
  )
}

/** 넓은 화면의 지도 정보 — 바닥 시트(끌 수 없는 손잡이가 달린) 대신 구성원 버튼 바로 아래에 붙는다. */
export function ProfileMenu({ mapId, trigger }: { mapId: string; trigger: ReactNode }) {
  const [confirm, setConfirm] = useState<Confirm>(null)
  return (
    <MenuPopover
      label="지도 정보"
      trigger={trigger}
      holdOpen={confirm !== null}
      overlay={<ProfileConfirm mapId={mapId} which={confirm} onCancel={() => setConfirm(null)} />}
    >
      <ProfileBody mapId={mapId} onConfirm={setConfirm} />
    </MenuPopover>
  )
}

function ProfileConfirm({ mapId, which, onCancel }: { mapId: string; which: Confirm; onCancel: () => void }) {
  const map = useMapQuery(mapId).data
  if (which === 'logout') return <LogoutConfirm onCancel={onCancel} />
  if (which === 'leave') return <LeaveMapConfirm mapId={mapId} nextOwnerName={map?.nextOwnerName} onCancel={onCancel} />
  if (which === 'delete' && map) return <DeleteMapConfirm mapId={mapId} title={map.title} onCancel={onCancel} />
  return null
}

/** 지도 정보 시트·메뉴 공통 내용 — 초대 링크, 구성원, 나가기·삭제, 계정. */
function ProfileBody({ mapId, onConfirm }: { mapId: string; onConfirm: (which: Confirm) => void }) {
  const map = useMapQuery(mapId)
  const members = useMembersQuery(mapId)
  const { url, status: inviteStatus, error: inviteError, retry: retryInvite, copied, copy, share } = useShareInvite(mapId)
  const me = useMeQuery()

  return (
    <>
      {map.data && (
        <header className="mb-4">
          <h2 className="text-xl font-bold text-ink-900">{map.data.title}</h2>
          <p className="text-sm text-ink-500">
            {map.data.dates} · 구성원 {map.data.memberCount}명
          </p>
        </header>
      )}
      {map.error && <ErrorText message="지도 정보를 불러오지 못했어요" error={map.error} />}

      <button
        type="button"
        onClick={() => void share()}
        disabled={inviteStatus !== 'ready'}
        className="btn-primary btn-lg w-full"
      >
        <Share size={20} aria-hidden="true" /> 초대 링크 공유하기
      </button>
      {/* 링크를 못 만들면 링크 줄 자리에 실패 문구와 「다시 시도」를 둔다(온보딩과 같은 규칙, #703). */}
      {inviteStatus === 'failed' ? (
        <div className="mt-2 flex items-center justify-between gap-2">
          <ErrorText message="초대 링크를 만들지 못했어요" error={inviteError} />
          <button type="button" onClick={retryInvite} className="btn-link shrink-0 text-sm">
            다시 시도
          </button>
        </div>
      ) : (
        <div className="mt-2 flex items-center justify-between gap-2 rounded-xl bg-ink-100 px-3 py-2.5 text-sm">
          <span className="truncate text-ink-600">{url ?? '링크를 만드는 중…'}</span>
          <button type="button" onClick={() => void copy()} disabled={!url} className="btn-link shrink-0">
            {copied ? '✓ 복사됨' : '복사'}
          </button>
        </div>
      )}

      <h3 className="mb-2 mt-6 text-sm font-bold text-ink-900">구성원</h3>
      {members.error && <ErrorText message="구성원을 불러오지 못했어요" error={members.error} />}
      <ul className="space-y-3">
        {members.data?.map((m) => (
          <li key={m.userId} className="flex items-center gap-3">
            {/* 구성원별 색 구분은 없다(#26) — 아바타는 회색 면 하나로 통일. */}
            <Avatar name={m.initial} />
            <span className="text-ink-900">
              {m.name}
              {m.isMe && <span className="ml-1 text-ink-500">(나)</span>}
            </span>
            {m.isOwner && <span className="tag tag-neutral">방장</span>}
          </li>
        ))}
      </ul>

      {map.data && (
        <div className="mt-6 flex gap-2 border-t border-ink-200 pt-4">
          {/* 넘길 사람이 없는 방장은 나갈 수 없다 — 나가기 자리에 이유를 적고 삭제를 안내한다. */}
          {map.data.canLeave ? (
            <button type="button" onClick={() => onConfirm('leave')} className="btn-neutral btn-md flex-1">
              지도 나가기
            </button>
          ) : (
            <p className="flex-1 self-center text-xs text-ink-500">혼자 남은 방장은 나갈 수 없어요. 대신 지도를 삭제할 수 있어요</p>
          )}
          {map.data.canDelete && (
            <button
              type="button"
              onClick={() => onConfirm('delete')}
              className="btn-danger-outline btn-md flex-1"
            >
              지도 삭제
            </button>
          )}
        </div>
      )}

      <div className="mt-4 flex items-center justify-between border-t border-ink-200 pt-4">
        <div>
          <p className="text-sm font-bold text-ink-900">계정</p>
          <p className="text-xs text-ink-500">
            {me.data?.is_guest ? <span className="tag tag-neutral mr-1">게스트</span> : '카카오로 로그인됨 · '}
            {me.data?.display_name}
          </p>
        </div>
        <button
          type="button"
          onClick={() => onConfirm('logout')}
          className="btn-neutral btn-sm"
        >
          로그아웃
        </button>
      </div>
      {me.data?.is_guest && <GuestAccountNotice />}
    </>
  )
}
