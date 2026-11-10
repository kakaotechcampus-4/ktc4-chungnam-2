import { useState, type ReactNode } from 'react'
import { Link, Navigate, useSearchParams } from 'react-router'
import { List, Settings, Users } from 'lucide-react'

import { AccountSection } from '@/features/maps/AccountSheet'
import { useMapsQuery } from '@/features/maps/queries'
import NotificationBell, { InboxHead, InboxList, PrefsHead, PrefsList } from '@/features/notifications/NotificationBell'
import { ProfileBody, ProfileConfirm, ProfileHead, type ProfileConfirmKind } from '@/features/shell/ProfileModal'
import { useShell } from '@/features/shell/shellContext'
import { useSheetStore } from '@/features/shell/sheetStore'
import TabSheet from '@/features/shell/TabSheet'
import { useIsDesktop } from '@/features/shell/useIsDesktop'
import BackButton from '@/ui/BackButton'
import SheetTitle from '@/ui/SheetTitle'

/** 프로필 탭 안에서 연 화면. 핀 상세처럼 주소에 둬서 휴대폰 뒤로 가기로 프로필에 돌아온다(#1710). */
const VIEW_PARAM = 'view'
type View = 'alerts' | 'alert-settings' | 'settings' | 'map'

/**
 * 프로필 탭(휴대폰만, 네이버 지도 MY 시안). 오른쪽 위까지 손이 닿지 않아도 알림, 내 지도 목록, 지도 정보, 계정을 아래에서 연다.
 * 시트 머리 오른쪽에 알림 종과 설정 톱니를 둔다(시안과 같은 자리).
 * 알림함, 설정, 지도 정보는 모달 시트를 겹쳐 띄우지 않고 이 시트의 머리와 내용을 그 화면으로 바꾼다(#1710).
 * 넓은 화면은 오른쪽 위 계정 원과 패널 머리에 같은 것이 있어 이 탭이 없다. 주소로 들어오면 핀 찍기 탭으로 보낸다.
 */
export default function MeTab() {
  const { mapId } = useShell()
  const desktop = useIsDesktop()
  const maps = useMapsQuery().data?.items ?? []
  const [params, setParams] = useSearchParams()
  const view = params.get(VIEW_PARAM) as View | null
  const stage = useSheetStore((s) => s.stages.me)
  const setStage = useSheetStore((s) => s.setStage)
  const [mapConfirm, setMapConfirm] = useState<ProfileConfirmKind>(null)

  if (desktop) return <Navigate to={`/maps/${mapId}`} replace />

  function go(next: View | null) {
    setParams((p) => {
      if (next) p.set(VIEW_PARAM, next)
      else p.delete(VIEW_PARAM)
      return p
    })
    // 접힌 시트에서 열면 내용이 보이게 절반까지 올린다.
    if (next && stage === 1) setStage('me', 2)
  }

  const back = <BackButton label="프로필" onClick={() => go(null)} />
  let header: ReactNode
  let body: ReactNode
  if (view === 'alerts') {
    header = <>{back}<InboxHead onSettings={() => go('alert-settings')} /></>
    // 시트 바탕은 흰 카드가 떠오르는 면이다. 이 지도 알림의 연한 파랑 면이 시트 바탕과 같은 색이라 흰 카드에 올린다.
    body = (
      <div className="overflow-hidden rounded-2xl bg-surface px-4">
        <InboxList currentMapId={mapId} />
      </div>
    )
  } else if (view === 'alert-settings') {
    header = <PrefsHead onBack={() => go('alerts')} />
    body = <PrefsList />
  } else if (view === 'settings') {
    header = <>{back}<SheetTitle>설정</SheetTitle></>
    body = <AccountSection maps={maps} mapId={mapId} settings />
  } else if (view === 'map') {
    // 지도 정보 머리(제목, 수정)와 내용이 확인 창 하나를 같이 쓴다.
    header = <>{back}<ProfileHead mapId={mapId} onConfirm={setMapConfirm} /></>
    body = (
      <>
        <ProfileBody mapId={mapId} onConfirm={setMapConfirm} />
        <ProfileConfirm mapId={mapId} which={mapConfirm} onCancel={() => setMapConfirm(null)} />
      </>
    )
  } else {
    header = (
      <div className="flex items-center justify-between gap-2">
        <SheetTitle>프로필</SheetTitle>
        <div className="flex items-center gap-3">
          <NotificationBell currentMapId={mapId} onOpen={() => go('alerts')} />
          <button
            type="button"
            aria-label="설정"
            onClick={() => go('settings')}
            className="hit-44 press flex size-8 shrink-0 items-center justify-center rounded-full border border-ink-200 bg-surface text-ink-900"
          >
            <Settings size={18} aria-hidden="true" />
          </button>
        </div>
      </div>
    )
    body = (
      <AccountSection
        maps={maps}
        mapId={mapId}
        links={
          <div className="mb-5 flex gap-2">
            <Link to="/" className="btn-neutral btn-md flex-1">
              <List size={18} aria-hidden="true" /> 내 지도 목록
            </Link>
            <button type="button" onClick={() => go('map')} className="btn-neutral btn-md flex-1">
              <Users size={18} aria-hidden="true" /> 지도 정보
            </button>
          </div>
        }
      />
    )
  }

  return (
    <TabSheet tab="me" header={header}>
      {body}
    </TabSheet>
  )
}
