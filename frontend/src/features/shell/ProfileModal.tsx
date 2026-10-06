import { useState } from 'react'
import { Share } from 'lucide-react'

import ErrorText from '@/ErrorText'
import LogoutConfirm from '@/features/auth/LogoutConfirm'
import { useMeQuery } from '@/features/auth/queries'
import { useMapQuery, useMembersQuery } from '@/features/maps/queries'
import { useShareInvite } from '@/features/maps/useShareInvite'

import ModalSheet from './ModalSheet'

/**
 * 프로필 모달(Figma 8절). 탭 시트가 아니라 모달이다 — 탭 시트 자리에 띄우면 켜진 탭과 내용이 어긋난다.
 * 검정 32% 딤이 지도·상단 버튼·하단 바까지 덮고, 시트는 화면 바닥에 붙는다.
 * 강퇴는 v2라 버튼이 없다.
 */
export default function ProfileModal({ mapId, onClose }: { mapId: string; onClose: () => void }) {
  const map = useMapQuery(mapId)
  const members = useMembersQuery(mapId)
  const { url, error: inviteError, copied, copy, share } = useShareInvite(mapId)
  const me = useMeQuery()
  const [confirmLogout, setConfirmLogout] = useState(false)

  return (
    <ModalSheet
      label="지도 정보"
      onClose={onClose}
      overlay={confirmLogout && <LogoutConfirm onCancel={() => setConfirmLogout(false)} />}
    >
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
        disabled={!url}
        className="flex w-full items-center justify-center gap-2 rounded-xl bg-brand-600 py-3 font-semibold text-white disabled:bg-ink-100 disabled:text-ink-400"
      >
        <Share size={18} aria-hidden="true" /> 초대 링크 공유하기
      </button>
      <div className="mt-2 flex items-center justify-between gap-2 rounded-lg bg-ink-100 px-3 py-2.5 text-sm">
        <span className="truncate text-ink-500">{url ?? '링크를 만드는 중…'}</span>
        <button type="button" onClick={() => void copy()} disabled={!url} className="shrink-0 font-semibold text-brand-600">
          {copied ? '✓ 복사됨' : '복사'}
        </button>
      </div>
      {inviteError && <ErrorText message="초대 링크를 만들지 못했어요" error={inviteError} />}

      <h3 className="mb-2 mt-6 font-semibold text-ink-900">구성원</h3>
      {members.error && <ErrorText message="구성원을 불러오지 못했어요" error={members.error} />}
      <ul className="space-y-3">
        {members.data?.map((m) => (
          <li key={m.userId} className="flex items-center gap-3">
            {/* 구성원별 색 구분은 없다(#26) — 아바타는 회색 면 하나로 통일. */}
            <span className="flex size-8 items-center justify-center rounded-full bg-ink-100 text-sm font-semibold text-ink-700">
              {m.initial}
            </span>
            <span className="text-ink-900">
              {m.name}
              {m.isMe && <span className="ml-1 text-ink-400">(나)</span>}
            </span>
            {m.isOwner && <span className="rounded-md bg-ink-100 px-1.5 py-0.5 text-[11px] font-semibold text-ink-600">방장</span>}
          </li>
        ))}
      </ul>

      <div className="mt-6 flex items-center justify-between border-t border-ink-200 pt-4">
        <div>
          <p className="text-sm font-semibold text-ink-900">계정</p>
          <p className="text-xs text-ink-500">카카오로 로그인됨 · {me.data?.display_name}</p>
        </div>
        <button
          type="button"
          onClick={() => setConfirmLogout(true)}
          className="rounded-lg border border-ink-300 px-3 py-1.5 text-sm font-semibold text-ink-900"
        >
          로그아웃
        </button>
      </div>
    </ModalSheet>
  )
}
