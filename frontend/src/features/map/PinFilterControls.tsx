import { ChevronDown } from 'lucide-react'

import type { MemberView } from '@/features/maps/model'

import { FILTER_CATEGORIES, SORTS, type Pin, type PinFilters, type PinSort } from './model'

/**
 * 카테고리 칩 줄(Figma 마킹 탭). 2단계까지는 지도 위 검색창 아래, 3단계에서는 시트 제목 아래에 놓인다.
 * 선택 상태는 채우지 않고 연한 배경 + 테두리(colors.md 6절 — 채움 버튼은 한 화면에 하나).
 */
export function CategoryChips({
  value,
  onChange,
  className = '',
}: {
  value: PinFilters['category']
  onChange: (category: string | null) => void
  className?: string
}) {
  const chips: { key: string | null; label: string }[] = [{ key: null, label: '전체' }, ...FILTER_CATEGORIES.map((c) => ({ key: c, label: c }))]
  return (
    <div role="group" aria-label="카테고리" className={`flex gap-2 overflow-x-auto py-1.5 ${className}`}>
      {chips.map((chip) => {
        const on = value === chip.key
        return (
          <button
            key={chip.label}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(chip.key)}
            className={`hit-y-44 shrink-0 rounded-full border px-3.5 py-1.5 text-sm shadow-sm ${
              on ? 'border-brand-600 bg-brand-100 font-semibold text-brand-700' : 'border-ink-200 bg-white text-ink-700'
            }`}
          >
            {chip.label}
          </button>
        )
      })}
    </div>
  )
}

/**
 * 「올린 사람 ▾」「의견 많은 순 ▾」 드롭다운. 구성원을 칩 줄로 만들면 카테고리 칩과 헷갈려서 드롭다운으로 했다.
 * 고르는 창은 브라우저 기본 select 를 쓴다 — 모바일에서 각 OS 의 고르기 화면이 뜬다.
 */
export function PinFilterBar({
  filters,
  members,
  pins,
  onChange,
}: {
  filters: PinFilters
  members: MemberView[]
  pins: Pin[]
  onChange: (key: 'by' | 'sort', value: string | null) => void
}) {
  const countBy = (userId: string) => pins.filter((p) => p.created_by === userId).length
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      <Pill label="올린 사람">
        <select
          aria-label="올린 사람"
          value={filters.createdBy ?? ''}
          onChange={(e) => onChange('by', e.target.value || null)}
          className="appearance-none bg-transparent pr-4 font-semibold text-ink-900 outline-none focus-visible:outline-2"
        >
          <option value="">전체 · {pins.length}곳</option>
          {members.map((m) => (
            <option key={m.userId} value={m.userId}>
              {m.name}
              {m.isMe ? ' (나)' : ''} · {countBy(m.userId)}곳
            </option>
          ))}
        </select>
      </Pill>
      <Pill>
        <select
          aria-label="정렬"
          value={filters.sort}
          onChange={(e) => onChange('sort', e.target.value === 'most' ? null : e.target.value)}
          className="appearance-none bg-transparent pr-4 font-semibold text-ink-900 outline-none focus-visible:outline-2"
        >
          {(Object.keys(SORTS) as PinSort[]).map((key) => (
            <option key={key} value={key}>
              {SORTS[key]}
            </option>
          ))}
        </select>
      </Pill>
    </div>
  )
}

function Pill({ label, children }: { label?: string; children: React.ReactNode }) {
  return (
    <label className="hit-y-44 relative flex min-h-8 items-center gap-1 whitespace-nowrap rounded-lg border border-ink-200 bg-white px-2.5 py-1 text-xs">
      {label && <span className="text-ink-500">{label}</span>}
      {children}
      <ChevronDown size={12} className="pointer-events-none absolute right-2 text-ink-500" aria-hidden="true" />
    </label>
  )
}
