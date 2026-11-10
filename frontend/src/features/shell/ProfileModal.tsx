import { useEffect, useState, type ReactNode } from 'react'
import { Share } from 'lucide-react'

import ErrorText from '@/ErrorText'
import PinTrashSheet from '@/features/map/PinTrashSheet'
import { othersOnline } from '@/features/maps/model'
import { useMapQuery, useMembersQuery } from '@/features/maps/queries'
import InviteLinks from '@/features/maps/InviteLinks'
import { DeleteMapConfirm, EditMapDialog, LeaveMapConfirm, TransferOwnerConfirm } from '@/features/maps/MapLifecycle'
import { useShareInvite } from '@/features/maps/useShareInvite'
import Avatar from '@/ui/Avatar'
import Sentences from '@/ui/Sentences'

import MenuPopover from './MenuPopover'
import ModalSheet from './ModalSheet'
import { useSheetStore } from './sheetStore'

type Confirm = 'leave' | 'delete' | 'edit' | 'owner' | 'trash' | null
/** 지도 정보에서 띄우는 확인 창. 휴대폰 프로필 탭은 머리와 내용을 탭 시트 두 자리에 나눠 넣고 이 상태를 같이 쓴다(#1710). */
export type ProfileConfirmKind = Confirm

/**
 * 프로필 모달(Figma 8절, 모바일). 탭 시트가 아니라 모달이다 — 탭 시트 자리에 띄우면 켜진 탭과 내용이 어긋난다.
 * 검정 32% 딤이 지도·상단 버튼·하단 바까지 덮고, 시트는 화면 바닥에 붙는다.
 * 넓은 화면은 같은 내용을 패널 헤더 구성원 버튼 아래 메뉴로 연다(ProfileMenu). 강퇴는 v2라 버튼이 없다.
 * 계정(이름, 로그아웃, 화면 모드, 도움 줄)은 휴대폰은 프로필 탭, 넓은 화면은 오른쪽 위 계정 원에 있다.
 */
export default function ProfileModal({ mapId, onClose }: { mapId: string; onClose: () => void }) {
  const [confirm, setConfirm] = useState<Confirm>(null)
  // 떠 있는 동안만 지도 버튼·토스트를 숨긴다. 닫기가 아니라 지도 나가기·삭제·화면 넓힘으로 사라져도 풀리게 마운트에 묶는다.
  const setModalOpen = useSheetStore((s) => s.setModalOpen)
  useEffect(() => {
    setModalOpen(true)
    return () => setModalOpen(false)
  }, [setModalOpen])
  return (
    <ModalSheet label="지도 정보" fullWidth onClose={onClose} overlay={<ProfileConfirm mapId={mapId} which={confirm} onCancel={() => setConfirm(null)} />}>
      <ProfileHead mapId={mapId} onConfirm={setConfirm} />
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
      <ProfileHead mapId={mapId} onConfirm={setConfirm} />
      <ProfileBody mapId={mapId} onConfirm={setConfirm} />
    </MenuPopover>
  )
}

export function ProfileConfirm({ mapId, which, onCancel }: { mapId: string; which: Confirm; onCancel: () => void }) {
  const map = useMapQuery(mapId).data
  const members = useMembersQuery(mapId).data
  if (which === 'leave') return <LeaveMapConfirm mapId={mapId} nextOwnerName={map?.nextOwnerName} onCancel={onCancel} />
  if (which === 'delete' && map) return <DeleteMapConfirm mapId={mapId} title={map.title} onCancel={onCancel} />
  if (which === 'edit' && map) return <EditMapDialog map={map} onCancel={onCancel} />
  if (which === 'owner' && members) return <TransferOwnerConfirm mapId={mapId} members={members} onCancel={onCancel} />
  if (which === 'trash') return <PinTrashSheet mapId={mapId} onClose={onCancel} />
  return null
}

/** 지도 정보 머리: 지도 제목, 날짜와 구성원 수, 수정. */
export function ProfileHead({ mapId, onConfirm }: { mapId: string; onConfirm: (which: Confirm) => void }) {
  const map = useMapQuery(mapId).data
  if (!map) return null
  return (
    <header className="mb-4 flex items-start justify-between gap-2">
      <div className="min-w-0">
        <h2 className="text-xl font-bold text-ink-900">{map.title}</h2>
        <p className="text-sm text-ink-500">
          {map.dates}, 구성원 {map.memberCount}명
        </p>
      </div>
      {/* 제목·날짜·지역 수정은 방장만(#465). */}
      {map.canEdit && (
        <button type="button" onClick={() => onConfirm('edit')} aria-label="지도 정보 수정" className="btn-link shrink-0">
          수정
        </button>
      )}
    </header>
  )
}

/** 지도 정보 시트와 메뉴 공통 내용: 초대 링크, 구성원, 핀 휴지통, 나가기와 삭제. */
export function ProfileBody({ mapId, onConfirm }: { mapId: string; onConfirm: (which: Confirm) => void }) {
  const map = useMapQuery(mapId)
  const members = useMembersQuery(mapId)
  const { url, token, status: inviteStatus, error: inviteError, retry: retryInvite, copied, copy, share } = useShareInvite(mapId)
  const isOwner = map.data?.isOwner === true

  return (
    <>
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
            {copied ? '복사됨' : '복사'}
          </button>
        </div>
      )}

      {/* 내가 지금 보이는 링크를 껐으면 새 링크를 만든다. */}
      {isOwner && <InviteLinks mapId={mapId} onRevoked={(t) => t === token && retryInvite()} />}

      <div className="mb-2 mt-6 flex items-center justify-between">
        <h3 className="text-sm font-bold text-ink-900">구성원</h3>
        {isOwner && members.data?.some((m) => !m.isMe && !m.isGuest) && (
          <button type="button" onClick={() => onConfirm('owner')} className="btn-link text-sm">
            방장 넘기기
          </button>
        )}
      </div>
      {members.error && <ErrorText message="구성원을 불러오지 못했어요" error={members.error} />}
      {/* 나 말고 지금 지도를 열어 둔 사람(#1551). 서버가 접속 상태를 주지 않으면 0이라 줄이 없다. */}
      {othersOnline(members.data) > 0 && <p className="mb-2 text-sm text-[var(--good-text)]">지금 {othersOnline(members.data)}명이 같이 보고 있어요</p>}
      <ul className="space-y-3">
        {members.data?.map((m) => (
          <li key={m.userId} className="flex items-center gap-3">
            {/* 구성원별 색 구분은 없다(#26) — 아바타는 회색 면 하나로 통일. */}
            <Avatar name={m.initial} online={m.online} />
            <span className="text-ink-900">
              {m.name}
              {m.isMe && <span className="ml-1 text-ink-500">(나)</span>}
            </span>
            {m.isOwner && <span className="tag tag-neutral">방장</span>}
            {m.isGuest && <span className="tag tag-neutral">게스트</span>}
            {m.opinionCount !== undefined && (
              <span className="ml-auto shrink-0 text-sm text-ink-500">{m.opinionCount > 0 ? `의견 ${m.opinionCount}개` : '아직 없음'}</span>
            )}
          </li>
        ))}
      </ul>

      {/* 삭제한 핀 되돌리기(#864). 내가 되돌릴 수 있는 핀만 보이고 비어 있을 수 있다. 조용한 글자 버튼이다(지도 휴지통 입구와 같다). */}
      <button type="button" onClick={() => onConfirm('trash')} className="btn-text mt-4 w-full text-center text-body">
        삭제한 핀
      </button>

      {map.data && (
        <div className="mt-4 flex gap-2 border-t border-ink-200 pt-4">
          {/* 넘길 사람이 없는 방장은 나갈 수 없다 — 나가기 자리에 이유를 적고 삭제를 안내한다. */}
          {map.data.canLeave ? (
            <button type="button" onClick={() => onConfirm('leave')} className="btn-neutral btn-md flex-1">
              지도 나가기
            </button>
          ) : (
            <p className="flex-1 self-center text-xs text-ink-500">
              <Sentences text="혼자 남은 방장은 나갈 수 없어요. 대신 지도를 삭제할 수 있어요" />
            </p>
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
    </>
  )
}

/** 계정 칸 아래 도움 줄(휴대폰 프로필 탭, 내 지도 목록 계정 시트): 자주 묻는 질문, 버그 신고하기, 의견 보내기. 넓은 화면은 ☰ 메뉴에 있다(#1538). */
export function HelpLinks({ onPick }: { onPick: (which: 'faq' | 'bug' | 'feedback') => void }) {
  return (
    <div className="mt-3 flex justify-center gap-4">
      <button type="button" onClick={() => onPick('faq')} className="btn-text text-body">
        자주 묻는 질문
      </button>
      <button type="button" onClick={() => onPick('bug')} className="btn-text text-body">
        버그 신고하기
      </button>
      <button type="button" onClick={() => onPick('feedback')} className="btn-text text-body">
        의견 보내기
      </button>
    </div>
  )
}
