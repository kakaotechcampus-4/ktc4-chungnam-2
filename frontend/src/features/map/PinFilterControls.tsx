import type { MemberView } from '@/features/maps/model'
import Select from '@/ui/Select'

import { FILTER_CATEGORIES, KINDS, kindLabel, OPINIONS, SORTS, type Pin, type PinFilters, type PinOpinion, type PinSort } from './model'

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
 * 고르는 목록은 `ui/Select`다 — 브라우저 기본 목록은 글자·색이 서비스와 따로 놀아서 바꿨다(#1695).
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
      <Select
        label="올린 사람"
        value={filters.createdBy ?? ''}
        onChange={(v) => onChange('by', v || null)}
        options={[
          { value: '', label: `전체 ${pins.length}곳` },
          ...members.map((m) => ({ value: m.userId, label: `${m.name}${m.isMe ? ' (나)' : ''} ${countBy(m.userId)}곳` })),
        ]}
      />
      <Select
        label="종류"
        value={filters.kind ?? ''}
        onChange={(v) => onChange('kind', v || null)}
        options={[{ value: '', label: '전체' }, ...KINDS.map((k) => ({ value: k, label: kindLabel(k) }))]}
      />
      <Select
        label="의견"
        value={filters.opinion ?? ''}
        onChange={(v) => onChange('opinion', v || null)}
        options={[{ value: '', label: '전체' }, ...(Object.keys(OPINIONS) as PinOpinion[]).map((key) => ({ value: key, label: OPINIONS[key] }))]}
      />
      <Select
        ariaLabel="정렬"
        value={filters.sort}
        onChange={(v) => onChange('sort', v === 'most' ? null : v)}
        options={(Object.keys(SORTS) as PinSort[]).map((key) => ({ value: key, label: SORTS[key] }))}
      />
    </div>
  )
}
