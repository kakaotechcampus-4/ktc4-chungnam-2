import { Link, Navigate } from 'react-router'

import ErrorText from '@/ErrorText'
import { readPendingInvite } from '@/features/auth/pendingInvite'
import { useMapsQuery } from '@/features/maps/queries'

/** 로그인 직후 진입점 — 내 지도 목록 (#24). */
export default function MapListPage() {
  // 초대 링크로 들어와 로그인한 사람은 목록 대신 그 초대로 보낸다.
  const pendingInvite = readPendingInvite()
  const { data: maps, isPending, error } = useMapsQuery()

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
      {error && <ErrorText message="지도를 불러오지 못했어요" error={error} />}
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
              <p className="text-xs text-muted-foreground">{map.summary}</p>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
