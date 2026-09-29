import { useQuery } from '@tanstack/react-query'
import { Link, Navigate } from 'react-router'
import type { components } from '@pingo/contracts/src/types/api'

import { api, ApiError } from '@/api'
import { readPendingInvite } from '@/features/auth/auth'

type MapInfo = components['schemas']['Map']

/** 로그인 직후 진입점 — 내 지도 목록 (#24). */
export default function MapListPage() {
  // 초대 링크로 들어와 로그인한 사람은 목록 대신 그 초대로 보낸다.
  const pendingInvite = readPendingInvite()
  const { data: maps, isPending, error } = useQuery({
    queryKey: ['maps'],
    queryFn: () => api<MapInfo[]>('/maps'),
  })

  if (pendingInvite) return <Navigate to={`/invites/${pendingInvite}`} replace />

  return (
    <div className="p-4">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-lg font-semibold">내 지도</h1>
        <Link to="/maps/new" className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground">
          새 지도
        </Link>
      </div>

      {isPending && <p className="text-sm text-muted-foreground">지도를 불러오는 중…</p>}
      {error && (
        <p className="text-sm text-destructive">
          지도를 불러오지 못했어요
          {error instanceof ApiError && <span className="ml-1 font-mono text-xs">({error.code})</span>}
        </p>
      )}
      {maps?.length === 0 && (
        <p className="text-sm text-muted-foreground">
          아직 속한 지도가 없어요. 새 지도를 만들거나 초대 링크로 들어오세요
        </p>
      )}

      <ul className="space-y-2">
        {maps?.map((map) => (
          <li key={map.id}>
            <Link to={`/maps/${map.id}`} className="block rounded-md border p-3">
              <p className="font-medium">{map.title}</p>
              <p className="text-xs text-muted-foreground">
                {map.start_date} ~ {map.end_date} · {map.member_count}명
              </p>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
