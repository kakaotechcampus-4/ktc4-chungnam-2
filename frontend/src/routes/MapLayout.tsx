import { Link, NavLink, Outlet, useParams } from 'react-router'

/** 최종기획안 4절 — 탭은 이 3개로 고정. 라벨도 고정 용어다(9절). */
const TABS = [
  { to: '', label: '지도', end: true },
  { to: 'recommend', label: 'AI 추천', end: false },
  { to: 'shortlist', label: '리스트', end: false },
]

/** 지도 하나 안의 화면들. 탭 3개가 모두 같은 `:mapId` 아래에 있다. */
export default function MapLayout() {
  const { mapId } = useParams()

  return (
    <>
      <Link to="/" className="block px-4 pt-3 text-sm text-muted-foreground">
        ← 내 지도
      </Link>

      <main className="pb-14">
        <Outlet />
      </main>

      <nav className="fixed inset-x-0 bottom-0 z-40 grid h-14 grid-cols-3 border-t bg-background">
        {TABS.map((tab) => (
          <NavLink
            key={tab.label}
            to={`/maps/${mapId}/${tab.to}`}
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
    </>
  )
}
