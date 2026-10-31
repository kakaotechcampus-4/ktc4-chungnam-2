import { useState } from 'react'
import { ChevronDown } from 'lucide-react'

import TextField, { ClearButton } from '@/ui/TextField'

import { tripDateError, type TripDraft } from './model'
import RegionPicker from './RegionPicker'

const TITLE_MAX = 100

/**
 * 지도의 제목·지역·날짜 입력(지도 만들기 #22, 지도 수정 #480). 지역은 선택이다.
 * 수정에서는 지역을 지울 수 없어서(서버가 바꾸기만 받는다, #465) `regionClearable`을 끈다.
 */
export default function TripFields({
  value,
  onChange,
  regionClearable = true,
}: {
  value: TripDraft
  onChange: (next: TripDraft) => void
  regionClearable?: boolean
}) {
  const [pickingRegion, setPickingRegion] = useState(false)
  const set = (patch: Partial<TripDraft>) => onChange({ ...value, ...patch })
  const dateError = tripDateError(value)

  return (
    <>
      <Field label="여행 제목">
        <TextField value={value.title} onChange={(title) => set({ title })} maxLength={TITLE_MAX} placeholder="예: 부산 1박 2일" clearLabel="제목 지우기" />
      </Field>

      <Field as="div" label={<>지역 <span className="font-normal text-ink-500">(선택)</span></>}>
        <div className="field">
          <button type="button" onClick={() => setPickingRegion(true)} className="min-w-0 flex-1 text-left">
            {value.region ? value.region.label : <span className="text-ink-500">시·도 선택</span>}
          </button>
          {value.region && regionClearable ? (
            <ClearButton label="지역 지우기" onClick={() => set({ region: null })} />
          ) : (
            <ChevronDown size={16} className="text-ink-500" aria-hidden="true" />
          )}
        </div>
        <p className="mt-1.5 text-xs text-ink-500">고르면 그 지역 장소 정보를 미리 준비해요</p>
      </Field>

      <div className="grid grid-cols-2 gap-2">
        <Field label="시작일">
          <input type="date" value={value.startDate} onChange={(e) => set({ startDate: e.target.value })} className="field w-full" />
        </Field>
        <Field label="종료일">
          <input
            type="date"
            value={value.endDate}
            min={value.startDate || undefined}
            onChange={(e) => set({ endDate: e.target.value })}
            aria-invalid={dateError}
            aria-describedby={dateError ? 'date-error' : undefined}
            // 입력 오류는 빨강이 아니라 주의색이다 — 빨강은 파괴적 동작 전용(colors.md 6절).
            className="field w-full"
          />
        </Field>
      </div>
      {dateError && (
        <p id="date-error" className="-mt-2 text-sm text-[var(--warn-text)]">
          종료일은 시작일과 같거나 뒤여야 해요
        </p>
      )}

      {pickingRegion && (
        <RegionPicker
          value={value.region}
          onClose={() => setPickingRegion(false)}
          onDone={(region) => {
            // 수정에서는 고른 지역을 다시 눌러 끄더라도 지역을 지우지 않는다.
            if (region || regionClearable) set({ region })
            setPickingRegion(false)
          }}
        />
      )}
    </>
  )
}

/** 입력칸 하나면 label 로 묶고, 버튼이 여럿이면(지역) div 로 둔다 — label 안에 버튼 여럿은 눌림이 엉킨다. */
function Field({ label, as: Tag = 'label', children }: { label: React.ReactNode; as?: 'label' | 'div'; children: React.ReactNode }) {
  return (
    <Tag className="mb-5 block">
      <span className="mb-1.5 block text-sm font-semibold text-ink-900">{label}</span>
      {children}
    </Tag>
  )
}
