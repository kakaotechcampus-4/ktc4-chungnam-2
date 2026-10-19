import { BrowserRouter, Route, Routes, useParams } from 'react-router'

import { USE_MOCK } from '@/api'
import ScenarioSwitcher from '@/dev/ScenarioSwitcher'
import RequireLogin from '@/features/auth/RequireLogin'
import InvitePage from '@/routes/InvitePage'
import LegalPage from '@/routes/LegalPage'
import MapCreatePage from '@/routes/MapCreatePage'
import MapLayout from '@/routes/MapLayout'
import MapListPage from '@/routes/MapListPage'
import MapTab from '@/routes/MapTab'
import RecommendTab from '@/routes/RecommendTab'
import ShortlistTab from '@/routes/ShortlistTab'

export default function App() {
  return (
    <BrowserRouter>
      {import.meta.env.DEV && USE_MOCK && <ScenarioSwitcher />}

      <Routes>
        {/* 초대 화면은 비로그인도 들어와야 해서 RequireLogin 밖에 둔다 (#23). */}
        <Route path="/invites/:token" element={<InvitePage />} />
        {/* 로그인 화면의 약관 동의 줄이 여는 문서라 이것도 비로그인으로 열린다 (#602). */}
        <Route path="/terms" element={<LegalPage title="이용약관" />} />
        <Route path="/privacy" element={<LegalPage title="개인정보처리방침" />} />

        <Route element={<RequireLogin />}>
          {/* 로그인 직후 진입점 = 내 지도 목록 (#24) */}
          <Route path="/" element={<MapListPage />} />
          <Route path="/maps/new" element={<MapCreatePage />} />
          <Route path="/maps/:mapId" element={<MapRoute />}>
            <Route index element={<MapTab />} />
            <Route path="recommend" element={<RecommendTab />} />
            <Route path="shortlist" element={<ShortlistTab />} />
          </Route>
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

/**
 * 지도를 바꾸면(패널 제목 메뉴) 지도 화면을 새로 띄운다 — 목록을 거쳐 들어온 것과 같게.
 * 같은 화면을 다시 쓰면 앞 지도의 검색어·패널 안 화면이 다음 지도에 남는다.
 */
function MapRoute() {
  const { mapId } = useParams()
  return <MapLayout key={mapId} />
}
