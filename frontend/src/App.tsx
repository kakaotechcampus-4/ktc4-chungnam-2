import { BrowserRouter, NavLink, Route, Routes } from 'react-router'

import ScenarioSwitcher from '@/dev/ScenarioSwitcher'
import MapTab from '@/routes/MapTab'
import RecommendTab from '@/routes/RecommendTab'
import ShortlistTab from '@/routes/ShortlistTab'

/** 최종기획안 4절 — 탭은 이 3개로 고정. 라벨도 고정 용어다(9절). */
const TABS = [
  { to: '/', label: '지도', end: true },
  { to: '/recommend', label: 'AI 추천', end: false },
  { to: '/shortlist', label: '리스트', end: false },
]

export default function App() {
  return (
    <BrowserRouter>
      {import.meta.env.DEV && <ScenarioSwitcher />}

      <main className="pb-14">
        <Routes>
          <Route path="/" element={<MapTab />} />
          <Route path="/recommend" element={<RecommendTab />} />
          <Route path="/shortlist" element={<ShortlistTab />} />
        </Routes>
      </main>

      <nav className="fixed inset-x-0 bottom-0 z-40 grid h-14 grid-cols-3 border-t bg-background">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.end}
            className={({ isActive }) =>
              `flex items-center justify-center text-sm ${
                isActive ? 'font-semibold text-foreground' : 'text-muted-foreground'
              }`
            }
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>
    </BrowserRouter>
  )
}
