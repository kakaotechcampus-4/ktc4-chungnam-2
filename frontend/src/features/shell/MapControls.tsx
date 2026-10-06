import { useEffect, useRef, useState, type ReactNode } from 'react'
import { History, LocateFixed, Scan } from 'lucide-react'

import { CONTROLS } from './layout'

export type ControlKey = 'locate' | 'recent' | 'fit'

const BUTTONS: { key: ControlKey; label: string; icon: ReactNode }[] = [
  { key: 'locate', label: '내 현재 위치로 이동', icon: <LocateFixed size={20} /> },
  { key: 'recent', label: '최근 핀으로 이동', icon: <History size={20} /> },
  { key: 'fit', label: '전체 핀 보기', icon: <Scan size={20} /> },
]

/**
 * 지도 버튼 3개(Figma 참고 '지도 버튼 3개'). 시트 윗변에 붙어서 시트와 같이 오르내린다.
 * 화면에 글자 설명은 붙이지 않는다 — aria-label 과 길게 누르면 뜨는 툴팁만 둔다.
 */
export default function MapControls({
  hidden,
  fading,
  active,
  onPress,
  onCrampedChange,
}: {
  /** 시트 3단계·모달 — 바로 숨긴다. */
  hidden: boolean
  /** 지도를 끄는 중 — 0.15초에 사라지고, 멈추면 0.8초 뒤 0.3초 동안 다시 나타난다. */
  fading: boolean
  active: ControlKey | null
  onPress: (key: ControlKey) => void
  /** 검색창·칩과 시트 사이가 버튼 묶음보다 좁아지면 true — 그때는 숨긴다(작은 화면·높은 시트, #308). */
  onCrampedChange: (cramped: boolean) => void
}) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const sheet = ref.current?.closest('section')
    const header = document.querySelector('[data-map-header]')
    if (!sheet || !header) return
    // 숨겨진 동안에도 잰다 — 버튼 자리가 아니라 시트 윗변과 상단 UI 아래끝 사이를 본다.
    // stackHeight 는 버튼 3개 + 시트와의 틈(12)이다. 상단 UI와는 4px만 떨어져 있으면 보인다(Figma 같은 식).
    const check = () =>
      onCrampedChange(sheet.getBoundingClientRect().top - CONTROLS.stackHeight < header.getBoundingClientRect().bottom + 4)
    check()
    const ro = new ResizeObserver(check)
    ro.observe(sheet)
    ro.observe(header)
    sheet.addEventListener('transitionend', check)
    window.addEventListener('resize', check)
    return () => {
      ro.disconnect()
      sheet.removeEventListener('transitionend', check)
      window.removeEventListener('resize', check)
    }
    // onCrampedChange 는 useState 의 setter 라 바뀌지 않는다.
  }, [onCrampedChange])

  return (
    <div
      ref={ref}
      hidden={hidden}
      style={{ right: CONTROLS.right }}
      className={`absolute bottom-[calc(100%+12px)] flex flex-col rounded-xl bg-white shadow-md transition-opacity ${
        fading ? 'pointer-events-none opacity-0 duration-150' : 'opacity-100 delay-800 duration-300'
      }`}
    >
      {BUTTONS.map((b, i) => (
        <ControlButton
          key={b.key}
          label={b.label}
          active={active === b.key}
          divider={i > 0}
          onPress={() => onPress(b.key)}
          tabIndex={fading ? -1 : 0}
        >
          {b.icon}
        </ControlButton>
      ))}
    </div>
  )
}

function ControlButton({
  label,
  active,
  divider,
  onPress,
  tabIndex,
  children,
}: {
  label: string
  active: boolean
  divider: boolean
  onPress: () => void
  tabIndex: number
  children: ReactNode
}) {
  const [tip, setTip] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const longPressed = useRef(false)

  const start = () => {
    longPressed.current = false
    timer.current = setTimeout(() => {
      longPressed.current = true
      setTip(true)
    }, 500)
  }
  const end = () => {
    clearTimeout(timer.current)
    setTip(false)
  }

  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      tabIndex={tabIndex}
      onPointerDown={start}
      onPointerUp={end}
      onPointerLeave={end}
      onContextMenu={(e) => e.preventDefault()}
      // 길게 눌러 설명만 본 경우엔 동작하지 않는다.
      onClick={() => !longPressed.current && onPress()}
      style={{ width: CONTROLS.size, height: CONTROLS.size }}
      className={`relative flex items-center justify-center first:rounded-t-xl last:rounded-b-xl ${
        divider ? 'border-t border-ink-100' : ''
      } ${active ? 'bg-brand-50 text-brand-600' : 'text-brand-600'}`}
    >
      {children}
      {tip && (
        <span className="absolute right-full mr-2 whitespace-nowrap rounded-md bg-ink-900 px-2 py-1 text-xs text-white">
          {label}
        </span>
      )}
    </button>
  )
}
