import SegmentedControl from '@/ui/SegmentedControl'

import { setThemeChoice, THEME_CHOICES, useThemeChoice } from './theme'

/** 「화면 모드」 고르기(#1412) — ☰ 메뉴 「설정」과 휴대폰 계정·지도 정보 시트에 같은 모양으로 둔다. */
export default function ThemeControl({ className = '' }: { className?: string }) {
  const choice = useThemeChoice()
  return (
    <div className={className}>
      <p className="mb-1.5 text-sm font-semibold text-ink-900">화면 모드</p>
      <SegmentedControl label="화면 모드" options={THEME_CHOICES} value={choice} onChange={setThemeChoice} />
    </div>
  )
}
