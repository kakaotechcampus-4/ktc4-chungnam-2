import { ChevronDown } from 'lucide-react'

import type { MemberView } from '@/features/maps/model'

import { FILTER_CATEGORIES, KINDS, OPINIONS, SORTS, type Pin, type PinFilters, type PinOpinion, type PinSort } from './model'

/**
 * 카테고리 칩 줄(Figma 마킹 탭). 2단계까지는 지도 위 검색창 아래, 3단계에서는 시트 제목 아래에 놓인다.
 * 선택 상태는 채우지 않고 연한 배경 + 테두리(colors.md 6절 — 채움 버튼은 한 화면에 하나).
 * 그림자는 지도 위에 떠 있을 때(`floating`)만 — 시트 안 틀에는 그림자를 넣지 않는다(DESIGN.md).
 */
export function CategoryChips({
  value,
  onChange,
  floating = false,
  className = '',
}: {
  value: PinFilters['category']
  onChange: (category: string | null) => void
  floating?: boolean
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
            className={`chip ${floating ? 'shadow-float' : ''}`}
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
  onChange: (key: 'by' | 'kind' | 'opinion' | 'sort', value: string | null) => void
}) {
  const countBy = (userId: string) => pins.filter((p) => p.created_by === userId).length
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      <FilterSelect
        label="올린 사람"
        value={filters.createdBy ?? ''}
        onChange={(v) => onChange('by', v || null)}
        options={[
          { value: '', label: `전체 · ${pins.length}곳` },
          ...members.map((m) => ({ value: m.userId, label: `${m.name}${m.isMe ? ' (나)' : ''} · ${countBy(m.userId)}곳` })),
        ]}
      />
      <FilterSelect
        label="종류"
        value={filters.kind ?? ''}
        onChange={(v) => onChange('kind', v || null)}
        options={[{ value: '', label: '전체' }, ...KINDS.map((k) => ({ value: k, label: k === 'AI추천' ? 'AI 추천' : k }))]}
      />
      <FilterSelect
        label="의견"
        value={filters.opinion ?? ''}
        onChange={(v) => onChange('opinion', v || null)}
        options={[{ value: '', label: '전체' }, ...(Object.keys(OPINIONS) as PinOpinion[]).map((key) => ({ value: key, label: OPINIONS[key] }))]}
      />
      <FilterSelect
        ariaLabel="정렬"
        value={filters.sort}
        onChange={(v) => onChange('sort', v === 'most' ? null : v)}
        options={(Object.keys(SORTS) as PinSort[]).map((key) => ({ value: key, label: SORTS[key] }))}
      />
    </div>
  )
}

/**
 * 필터 드롭다운 한 칸. 보이는 건 「라벨 값 ▾」 글자이고, 그 위에 투명한 select 를 칸 전체(위아래로 넓힌 44px 포함)에 겹친다.
 * 칸 어디를 눌러도 select 가 눌린다 — 넓힌 영역(::before)이 select 를 덮으면 label 만 눌려 목록이 안 열리고,
 * 모바일에서는 시트 제목 줄이 그 누름을 끌기·접기로 받아 시트가 접혔다(#600).
 */
function FilterSelect({
  label,
  ariaLabel = label,
  value,
  options,
  onChange,
}: {
  /** 칸 앞에 붙는 회색 글자. 정렬처럼 값만으로 읽히면 없다. */
  label?: string
  ariaLabel?: string
  value: string
  options: { value: string; label: string }[]
  onChange: (value: string) => void
}) {
  const current = options.find((o) => o.value === value) ?? options[0]
  return (
    <div className="relative flex h-8 items-center gap-1 whitespace-nowrap rounded-md border border-ink-200 bg-white pl-2.5 pr-6 text-xs has-[select:focus-visible]:outline-2 has-[select:focus-visible]:outline-offset-2 has-[select:focus-visible]:outline-[var(--line-focus)]">
      {/* 읽어 주는 건 select(이름 + 고른 값)가 맡는다 — 보이는 글자는 스크린리더에서 뺀다. */}
      {label && (
        <span aria-hidden="true" className="text-ink-500">
          {label}
        </span>
      )}
      <span aria-hidden="true" className="font-semibold text-ink-900">
        {current?.label}
      </span>
      <ChevronDown size={12} className="pointer-events-none absolute right-2 text-ink-500" aria-hidden="true" />
      <select
        aria-label={ariaLabel}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="absolute inset-x-0 -inset-y-1.5 cursor-pointer appearance-none opacity-0"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  )
}
