import { useState } from 'react'
import { useNavigate } from 'react-router'
import { Bell } from 'lucide-react'

import ErrorText from '@/ErrorText'
import { timeAgo } from '@/features/map/model'
import ModalSheet from '@/features/shell/ModalSheet'
import BackButton from '@/ui/BackButton'
import CardSkeleton from '@/ui/CardSkeleton'
import EmptyState from '@/ui/EmptyState'
import SheetTitle from '@/ui/SheetTitle'
import Switch from '@/ui/Switch'

import { badgeText, notificationTarget, prefLabel, type NotificationDto } from './model'
import { useMarkReadMutation, useNotificationPrefsQuery, useNotificationsQuery, useUpdatePrefMutation } from './queries'

/**
 * 종 버튼과 알림함(#483). 안 읽은 수는 파랑 배지(할 일 표시는 파랑, DESIGN.md)로 보인다.
 * `floating`은 지도 위(흰 원 + 그림자), 아니면 입구 화면·넓은 화면 패널 머리의 테두리 원이다.
 */
export default function NotificationBell({ floating = false }: { floating?: boolean }) {
  const [open, setOpen] = useState(false)
  const list = useNotificationsQuery()
  const unread = list.data?.pages[0]?.unread_count ?? 0
  const badge = badgeText(unread)

  return (
    <>
      <button
        type="button"
        aria-label={badge ? `알림 · 안 읽은 알림 ${badge}개` : '알림'}
        onClick={() => {
          setOpen(true)
          // 알림함을 열 때 새로 받는다 — 실시간 푸시가 없다(api-spec GET /me/notifications).
          void list.refetch()
        }}
        className={`hit-44 relative flex size-8 shrink-0 items-center justify-center rounded-full bg-white text-ink-900 ${
          floating ? 'pointer-events-auto shadow-float' : 'border border-ink-200 hover:bg-ink-50'
        }`}
      >
        <Bell size={18} aria-hidden="true" />
        {badge && (
          <span aria-hidden="true" className="absolute -right-1.5 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-brand-600 px-1 text-label text-white ring-2 ring-white">
            {badge}
          </span>
        )}
      </button>
      {open && <NotificationSheet onClose={() => setOpen(false)} />}
    </>
  )
}

function NotificationSheet({ onClose }: { onClose: () => void }) {
  const [settings, setSettings] = useState(false)
  return (
    <ModalSheet label="알림" onClose={onClose}>
      {settings ? <PrefsView onBack={() => setSettings(false)} /> : <InboxView onClose={onClose} onSettings={() => setSettings(true)} />}
    </ModalSheet>
  )
}

function InboxView({ onClose, onSettings }: { onClose: () => void; onSettings: () => void }) {
  const list = useNotificationsQuery()
  const markRead = useMarkReadMutation()
  const navigate = useNavigate()
  const items = list.data?.pages.flatMap((p) => p.items) ?? []
  const unread = list.data?.pages[0]?.unread_count ?? 0

  function open(n: NotificationDto) {
    if (!n.read) markRead.mutate([n.id])
    onClose()
    navigate(notificationTarget(n))
  }

  return (
    <>
      <div className="mb-3 flex items-center justify-between gap-2">
        <SheetTitle>알림</SheetTitle>
        <div className="flex shrink-0 items-center gap-3">
          {unread > 0 && (
            <button type="button" onClick={() => markRead.mutate(undefined)} disabled={markRead.isPending} className="btn-link text-body">
              모두 읽음
            </button>
          )}
          <button type="button" onClick={onSettings} className="btn-link text-body">
            설정
          </button>
        </div>
      </div>

      {list.isPending && <CardSkeleton count={2} />}
      {list.error && <ErrorText message="알림을 불러오지 못했어요" error={list.error} />}
      {list.data && items.length === 0 && <EmptyState title="아직 알림이 없어요">내 핀에 의견이 달리거나 구성원이 들어오면 여기 모여요</EmptyState>}

      <ul className="-mx-4 divide-y divide-ink-100">
        {items.map((n) => (
          <li key={n.id}>
            {/* 문장은 서버가 만든 그대로 보인다 — 화면이 이름·사유를 끼워 문장을 짓지 않는다(#717). */}
            <button type="button" onClick={() => open(n)} className="flex w-full items-start gap-2 px-4 py-3 text-left hover:bg-ink-50">
              <span aria-hidden="true" className={`mt-1.5 size-2 shrink-0 rounded-full ${n.read ? '' : 'bg-brand-600'}`} />
              <span className="min-w-0 flex-1">
                <span className={`block text-body ${n.read ? 'text-ink-600' : 'font-semibold text-ink-900'}`}>
                  {!n.read && <span className="sr-only">안 읽음 · </span>}
                  {n.message}
                </span>
                <span className="mt-0.5 block text-xs text-ink-500">
                  {n.map_title ? `${n.map_title} · ` : ''}
                  {timeAgo(n.created_at)}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>

      {list.hasNextPage && (
        <button type="button" onClick={() => void list.fetchNextPage()} disabled={list.isFetchingNextPage} className="btn-text mt-2 w-full text-center text-body">
          {list.isFetchingNextPage ? '불러오는 중…' : '이전 알림 더 보기'}
        </button>
      )}
      {list.isFetchNextPageError && <ErrorText message="이전 알림을 불러오지 못했어요" error={list.error} />}
    </>
  )
}

function PrefsView({ onBack }: { onBack: () => void }) {
  const prefs = useNotificationPrefsQuery()
  const update = useUpdatePrefMutation()

  return (
    <>
      <BackButton label="알림" onClick={onBack} />
      <SheetTitle>알림 설정</SheetTitle>
      <p className="mb-3 mt-1 text-xs text-ink-500">끄면 앞으로 그 알림을 만들지 않아요. 이미 온 알림은 남아요.</p>
      {prefs.isPending && <CardSkeleton count={1} />}
      {prefs.error && <ErrorText message="알림 설정을 불러오지 못했어요" error={prefs.error} />}
      <ul className="divide-y divide-ink-100">
        {prefs.data?.map((p) => (
          <li key={p.type} className="flex items-center justify-between gap-3 py-2">
            <span className="text-body text-ink-900">{prefLabel(p.type)}</span>
            <Switch
              checked={p.enabled}
              label={prefLabel(p.type)}
              disabled={update.isPending}
              onChange={(enabled) => update.mutate({ type: p.type, enabled })}
            />
          </li>
        ))}
      </ul>
      {update.error && <ErrorText message="알림 설정을 바꾸지 못했어요" error={update.error} />}
    </>
  )
}
