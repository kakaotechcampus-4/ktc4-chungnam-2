import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { Share } from 'lucide-react'

import ErrorText from '@/ErrorText'
import { useLogoutMutation, useMeQuery } from '@/features/auth/queries'
import { useInviteQuery, useMapQuery, useMembersQuery } from '@/features/maps/queries'

import { showToast } from './toast'
import Toaster from './Toaster'

/**
 * 프로필 모달(Figma 8절). 탭 시트가 아니라 모달이다 — 탭 시트 자리에 띄우면 켜진 탭과 내용이 어긋난다.
 * 검정 32% 딤이 지도·상단 버튼·하단 바까지 덮고, 시트는 화면 바닥에 붙는다.
 * 강퇴는 v2라 버튼이 없다. 방장 표시는 구성원 응답에 역할 필드가 없어 아직 못 붙인다.
 */
export default function ProfileModal({ mapId, onClose }: { mapId: string; onClose: () => void }) {
  const navigate = useNavigate()
  const map = useMapQuery(mapId)
  const members = useMembersQuery(mapId)
  const invite = useInviteQuery(mapId, true)
  const me = useMeQuery()
  const logout = useLogoutMutation()
  const [copied, setCopied] = useState(false)
  const [confirmLogout, setConfirmLogout] = useState(false)

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const url = invite.data?.url

  async function copy() {
    if (!url) return
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      showToast('초대 링크를 복사했어요')
    } catch (err) {
      console.error('[profile] 링크 복사 실패', err)
      showToast('링크를 복사하지 못했어요. 길게 눌러 직접 복사해 주세요')
    }
  }

  async function share() {
    if (!url) return
    // 공유 창이 없는 브라우저(데스크톱 대부분)는 복사로 대신한다.
    if (!navigator.share) return copy()
    try {
      await navigator.share({ title: map.data?.title, url })
    } catch (err) {
      // 사용자가 공유 창을 닫은 건 실패가 아니다.
      if (err instanceof DOMException && err.name === 'AbortError') return
      console.error('[profile] 공유 실패', err)
      void copy()
    }
  }

  return (
    <div className="fixed inset-0 z-50">
      <button type="button" aria-label="닫기" onClick={onClose} className="absolute inset-0 bg-black/32" />
      {/* 토스트가 시트 윗변 위에 떠야 해서, 스크롤되는 시트 바깥 틀에 붙인다. */}
      <div className="absolute inset-x-0 bottom-0">
        <Toaster controlsVisible={false} />
      <section
        role="dialog"
        aria-modal="true"
        aria-label="지도 정보"
        className="max-h-[90dvh] overflow-y-auto rounded-t-2xl bg-white px-4 pb-[34px] pt-2"
      >
        <div className="mx-auto mb-4 h-1 w-12 rounded-full bg-ink-300" aria-hidden="true" />

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
        {invite.error && <ErrorText message="초대 링크를 만들지 못했어요" error={invite.error} />}

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
      </section>
      </div>

      {confirmLogout && (
        <div role="alertdialog" aria-modal="true" aria-label="로그아웃 확인" className="absolute inset-0 flex items-center justify-center bg-black/32 p-6">
          <div className="w-full max-w-sm rounded-2xl bg-white p-5">
            <p className="font-semibold text-ink-900">로그아웃할까요?</p>
            <p className="mt-1 text-sm text-ink-500">
              지도와 핀은 그대로 남아요. 다시 들어오려면 카카오로 로그인하면 돼요.
            </p>
            {logout.error && <ErrorText message="로그아웃하지 못했어요" error={logout.error} />}
            <div className="mt-4 grid grid-cols-2 gap-2">
              <button type="button" onClick={() => setConfirmLogout(false)} className="rounded-lg border border-ink-300 py-2 text-sm">
                취소
              </button>
              <button
                type="button"
                disabled={logout.isPending}
                onClick={() => logout.mutate(undefined, { onSuccess: () => navigate('/', { replace: true }) })}
                className="rounded-lg bg-brand-600 py-2 text-sm font-semibold text-white disabled:opacity-50"
              >
                로그아웃
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
