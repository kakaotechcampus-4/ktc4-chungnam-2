import { useState } from 'react'
import { Link, Navigate } from 'react-router'
import { Map as MapIcon, Plus } from 'lucide-react'

import ErrorText from '@/ErrorText'
import { readPendingInvite } from '@/features/auth/pendingInvite'
import { useMeQuery } from '@/features/auth/queries'
import AccountSheet from '@/features/maps/AccountSheet'
import type { MapView } from '@/features/maps/model'
import { useMapsQuery } from '@/features/maps/queries'

/** 로그인 직후 진입점 — 내 지도 목록 (#24, Figma 1절). 빈 목록은 AI와 관계없는 화면이라 핑고를 넣지 않는다. */
export default function MapListPage() {
  // 초대 링크로 들어와 로그인한 사람은 목록 대신 그 초대로 보낸다.
  const pendingInvite = readPendingInvite()
  const { data: maps, isPending, error } = useMapsQuery()
  const me = useMeQuery().data
  const [accountOpen, setAccountOpen] = useState(false)

  const invited = (maps ?? []).filter((m) => m.createdByMe === false)
  const mine = (maps ?? []).filter((m) => m.createdByMe !== false)

  if (pendingInvite) return <Navigate to={`/invites/${pendingInvite}`} replace />

  return (
    <div className="mx-auto flex min-h-dvh w-full max-w-[480px] flex-col bg-ink-50 px-4 pb-6 pt-6">
      <header className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-ink-900">내 지도</h1>
        <button
          type="button"
          aria-label="계정"
          onClick={() => setAccountOpen(true)}
          className="hit-44 flex size-8 items-center justify-center rounded-full bg-brand-600 text-sm font-semibold text-white"
        >
          {me?.display_name?.slice(0, 1)}
        </button>
      </header>

      {isPending && <p className="text-sm text-ink-500">지도를 불러오는 중…</p>}
      {error && <ErrorText message="지도를 불러오지 못했어요" error={error} />}

      {maps?.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center text-center">
          <span className="mb-3 flex size-16 items-center justify-center rounded-2xl bg-ink-100 text-ink-400">
            <MapIcon size={28} aria-hidden="true" />
          </span>
          <p className="font-semibold text-ink-900">아직 만든 지도가 없어요</p>
          <p className="mt-1 text-sm text-ink-500">지도를 만들고 친구를 초대해 보세요</p>
        </div>
      ) : (
        <div className="flex-1 space-y-5">
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

      <Link
        to="/maps/new"
        className="btn-primary sticky bottom-6 mt-4 flex items-center justify-center gap-1 py-3.5"
      >
        <Plus size={18} aria-hidden="true" /> 새 지도 만들기
      </Link>

      {accountOpen && <AccountSheet maps={maps ?? []} onClose={() => setAccountOpen(false)} />}
    </div>
  )
}

function MapSection({ title, maps, empty }: { title?: string; maps: MapView[]; empty?: string }) {
  return (
    <section className="space-y-3">
      {title && <h2 className="text-sm font-semibold text-ink-600">{title}</h2>}
      {maps.length === 0 && empty && <p className="rounded-2xl bg-white p-4 text-sm text-ink-500">{empty}</p>}
      <ul className="space-y-3">
        {maps.map((map) => (
          <li key={map.id}>
            <Link to={`/maps/${map.id}`} className="block rounded-2xl border border-ink-200 bg-white p-4">
              <p className="flex items-center gap-2">
                <span className="truncate text-lg font-bold text-ink-900">{map.title}</span>
                {map.isOwner && <span className="shrink-0 rounded-md bg-brand-50 px-1.5 py-0.5 text-[0.6875rem] font-semibold text-brand-600">방장</span>}
                {map.region && (
                  <span className="shrink-0 rounded-md bg-ink-100 px-1.5 py-0.5 text-[0.6875rem] text-ink-500">{map.region}</span>
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
