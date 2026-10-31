import { useId, useState } from 'react'
import { Link, Navigate } from 'react-router'
import { Plus } from 'lucide-react'

import ErrorText from '@/ErrorText'
import { readPendingInvite } from '@/features/auth/pendingInvite'
import { useMeQuery } from '@/features/auth/queries'
import AccountSheet, { AccountMenu } from '@/features/maps/AccountSheet'
import { MAP_LIMIT_HINT, type MapListView, type MapView } from '@/features/maps/model'
import { useMapsQuery } from '@/features/maps/queries'
import NotificationBell from '@/features/notifications/NotificationBell'
import { hasSeenWelcome } from '@/features/onboarding/welcomeSeen'
import Toaster from '@/features/shell/Toaster'
import { useIsDesktop } from '@/features/shell/useIsDesktop'
import Avatar from '@/ui/Avatar'
import CardSkeleton from '@/ui/CardSkeleton'
import EmptyState from '@/ui/EmptyState'

/**
 * 로그인 직후 진입점 — 내 지도 목록 (#24, Figma 1절).
 * 넓은 화면(768px 이상)은 가운데 좁은 띠 대신 넓은 틀에 카드를 격자로 깔고, 「새 지도 만들기」는 헤더 오른쪽,
 * 계정은 바닥 시트 대신 계정 버튼 아래 메뉴다. 지도에 들어간 뒤 다른 지도로 옮기는 건 패널 제목 메뉴가 맡는다.
 * 제목 아래 "지도 n / 상한"의 상한은 목록 응답의 limit이고(#623), 상한까지 차면 「새 지도 만들기」를 막는다.
 */
export default function MapListPage() {
  // 초대 링크로 들어와 로그인한 사람은 목록 대신 그 초대로 보낸다.
  const pendingInvite = readPendingInvite()
  const { data: list, isPending, error } = useMapsQuery()
  const maps = list?.items
  const full = list?.full === true
  const limitHintId = useId()
  const me = useMeQuery().data
  const desktop = useIsDesktop()
  const [accountOpen, setAccountOpen] = useState(false)

  const invited = (maps ?? []).filter((m) => m.createdByMe === false)
  const mine = (maps ?? []).filter((m) => m.createdByMe !== false)

  // 이 기기에서 처음이면 기능 소개부터 — 끝나면 여기로 돌아와 초대가 있으면 그리로 간다.
  if (!hasSeenWelcome()) return <Navigate to="/welcome" replace />
  if (pendingInvite) return <Navigate to={`/invites/${pendingInvite}`} replace />

  return (
    <div className="min-h-dvh bg-ink-50">
      <div className="mx-auto flex min-h-dvh w-full max-w-[480px] flex-col px-4 pb-6 pt-6 md:max-w-5xl md:px-8 md:pb-16 md:pt-12">
        <header className="mb-4 flex items-center justify-between gap-4 md:mb-8">
          <div className="min-w-0">
            <h1 className="text-2xl font-bold text-ink-900">내 지도</h1>
            <MapCount list={list} hintId={full ? limitHintId : undefined} />
          </div>
          {desktop ? (
            <div className="flex shrink-0 items-center gap-3">
              <NewMapLink className="btn-md" blockedBy={full ? limitHintId : undefined} />
              <NotificationBell />
              <AccountMenu maps={maps ?? []} name={me?.display_name} />
            </div>
          ) : (
            <div className="flex shrink-0 items-center gap-3">
              <NotificationBell />
              <button
                type="button"
                aria-label="계정"
                onClick={() => setAccountOpen(true)}
                className="hit-44 rounded-full"
              >
                <Avatar name={me?.display_name} />
              </button>
            </div>
          )}
        </header>

        {isPending && <CardSkeleton count={2} />}
        {error && <ErrorText message="지도를 불러오지 못했어요" error={error} />}

        {maps?.length === 0 ? (
          <div className="flex flex-1 flex-col justify-center md:flex-none md:rounded-2xl md:border md:border-dashed md:border-ink-300 md:py-18">
            <EmptyState title="아직 만든 지도가 없어요">
              지도를 만들고 친구를 초대해 보세요
            </EmptyState>
          </div>
        ) : (
          <div className="flex-1 space-y-5 md:space-y-10">
            {/* 내가 만든 지도와 초대받은 지도를 나눈다(회의 14번). 초대받은 지도가 없거나 서버가 아직 구분을 안 주면 한 목록이다. */}
            {invited.length > 0 ? (
              <>
                <MapSection title="내가 만든 지도" maps={mine} empty="아직 만든 지도가 없어요" />
                <MapSection title="초대받은 지도" maps={invited} />
              </>
            ) : (
              <MapSection maps={mine} />
            )}
          </div>
        )}

        {/* 모바일은 엄지가 닿는 바닥에 붙는다. 넓은 화면은 헤더 오른쪽에 있다. */}
        {!desktop && <NewMapLink className="btn-lg sticky bottom-6 mt-4" blockedBy={full ? limitHintId : undefined} />}
      </div>

      {accountOpen && !desktop && <AccountSheet maps={maps ?? []} onClose={() => setAccountOpen(false)} />}
      {/* 넓은 화면 계정 메뉴의 「링크 복사」 토스트 자리 — 화면 바닥 가운데. 모바일은 계정 시트가 토스트를 갖고 있다. */}
      {desktop && (
        <div className="pointer-events-none fixed inset-0 z-[60]">
          <Toaster docked controlsVisible={false} />
        </div>
      )}
    </div>
  )
}

/**
 * "지도 n / 상한". 받기 전에도 min-h-5 로 줄 높이를 잡아 둬서 값이 들어올 때 아래 목록이 밀리지 않는다(CLS).
 * 상한일 때 안내는 모바일·넓은 화면 모두 이 줄 끝에 붙인다 — 바닥에 따로 두면 컴포넌트 목록에 없는 상자가 필요하다.
 */
function MapCount({ list, hintId }: { list?: MapListView; hintId?: string }) {
  return (
    <p className="mt-1 min-h-5 text-sm text-ink-500">
      {list && (
        <>
          지도 <span aria-hidden="true">{list.items.length} / {list.limit}</span>
          <span className="sr-only">{list.limit}개 중 {list.items.length}개</span>
          {hintId && <> · <span id={hintId}>{MAP_LIMIT_HINT}</span></>}
        </>
      )}
    </p>
  )
}

/**
 * 한 화면 한 채움 — 이 화면의 채움 버튼은 이것 하나다. 상한이면 막고 안내(blockedBy)를 읽게 한다.
 * 막아도 /maps/new 로 바로 들어오는 길은 남아 있어서, 그때는 409 MAP_LIMIT 문구가 맡는다.
 */
function NewMapLink({ className, blockedBy }: { className: string; blockedBy?: string }) {
  const body = (
    <>
      <Plus size={18} aria-hidden="true" /> 새 지도 만들기
    </>
  )
  const look = `btn-primary ${className}` // 정렬과 간격은 크기 클래스(btn-md, btn-lg)가 맡는다(#626)
  if (blockedBy) {
    return (
      <button type="button" disabled aria-describedby={blockedBy} className={look}>
        {body}
      </button>
    )
  }
  return (
    <Link to="/maps/new" className={look}>
      {body}
    </Link>
  )
}

function MapSection({ title, maps, empty }: { title?: string; maps: MapView[]; empty?: string }) {
  return (
    <section className="space-y-3">
      {title && (
        <h2 className="text-sm font-bold text-ink-900">
          {title}
          {/* 넓은 화면은 한눈에 여러 줄이 보여서 몇 개인지 같이 적는다. */}
          <span className="ml-1 hidden font-normal text-ink-500 md:inline">{maps.length}</span>
        </h2>
      )}
      {maps.length === 0 && empty && <p className="rounded-xl bg-white p-4 text-sm text-ink-500">{empty}</p>}
      <ul className="space-y-3 md:grid md:grid-cols-2 md:gap-4 md:space-y-0 lg:grid-cols-3">
        {maps.map((map) => (
          <li key={map.id}>
            <Link
              to={`/maps/${map.id}`}
              className="block h-full rounded-xl border border-ink-200 bg-white p-4 transition-colors md:p-5 md:hover:border-brand-300"
            >
              <p className="flex items-center gap-2">
                <span className="truncate text-title font-bold text-ink-900">{map.title}</span>
                {map.isOwner && <span className="tag tag-neutral">방장</span>}
                {map.region && (
                  <span className="tag tag-neutral">{map.region}</span>
                )}
              </p>
              <p className="mt-1 text-sm text-ink-500">{map.summary}</p>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}
