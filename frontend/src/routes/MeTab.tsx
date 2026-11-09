import { useState } from 'react'
import { Link, Navigate } from 'react-router'
import { List, Users } from 'lucide-react'

import { AccountSection } from '@/features/maps/AccountSheet'
import { useMapsQuery } from '@/features/maps/queries'
import NotificationBell from '@/features/notifications/NotificationBell'
import ProfileModal from '@/features/shell/ProfileModal'
import { useShell } from '@/features/shell/shellContext'
import TabSheet from '@/features/shell/TabSheet'
import { useIsDesktop } from '@/features/shell/useIsDesktop'
import SheetTitle from '@/ui/SheetTitle'

/**
 * 「내 프로필」 탭(휴대폰만, 네이버 지도 MY 시안). 오른쪽 위까지 손이 닿지 않아도 알림, 내 지도 목록, 지도 정보, 계정을 아래에서 연다.
 * 넓은 화면은 오른쪽 위 계정 원과 패널 머리에 같은 것이 있어 이 탭이 없다 — 주소로 들어오면 핀 찍기 탭으로 보낸다.
 */
export default function MeTab() {
  const { mapId } = useShell()
  const desktop = useIsDesktop()
  const maps = useMapsQuery().data?.items ?? []
  const [mapInfo, setMapInfo] = useState(false)

  if (desktop) return <Navigate to={`/maps/${mapId}`} replace />

  return (
    <TabSheet
      tab="me"
      header={
        <div className="flex items-center justify-between gap-2">
          <SheetTitle>내 프로필</SheetTitle>
          <NotificationBell currentMapId={mapId} />
        </div>
      }
    >
      <AccountSection
        maps={maps}
        mapId={mapId}
        links={
          <div className="mb-5 flex gap-2">
            <Link to="/" className="btn-neutral btn-md flex-1">
              <List size={18} aria-hidden="true" /> 내 지도 목록
            </Link>
            <button type="button" onClick={() => setMapInfo(true)} className="btn-neutral btn-md flex-1">
              <Users size={18} aria-hidden="true" /> 지도 정보
            </button>
          </div>
        }
      />
      {mapInfo && <ProfileModal mapId={mapId} onClose={() => setMapInfo(false)} />}
    </TabSheet>
  )
}
