import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { ChevronDown, ChevronLeft } from 'lucide-react'

import ErrorText from '@/ErrorText'
import { createMapErrorMessage, type MapRegion } from '@/features/maps/model'
import { useCreateMapMutation } from '@/features/maps/queries'
import RegionPicker from '@/features/maps/RegionPicker'
import TextField, { ClearButton } from '@/ui/TextField'

const TITLE_MAX = 100

/**
 * 지도 만들기 (#22, Figma 1절). 제목·날짜는 필수, 지역은 선택(시·도 목록).
 * 빈 칸이 있거나 종료일이 시작일보다 앞서면 버튼이 꺼진다. 당일치기는 같은 날을 넣는다.
 */
export default function MapCreatePage() {
  const navigate = useNavigate()
  const create = useCreateMapMutation()
  const [title, setTitle] = useState('')
  const [region, setRegion] = useState<MapRegion | null>(null)
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [pickingRegion, setPickingRegion] = useState(false)

  // ISO 날짜 문자열은 사전순 비교가 곧 날짜 비교다.
  const dateError = Boolean(startDate && endDate && endDate < startDate)
  const ready = title.trim() !== '' && startDate !== '' && endDate !== '' && !dateError

  function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!ready) return
    create.mutate(
      { title: title.trim(), start_date: startDate, end_date: endDate, ...(region ? { region } : {}) },
      // 방장 온보딩(Figma 3절)은 지도 화면이 이 표시를 보고 띄운다.
      { onSuccess: (map) => navigate(`/maps/${map.id}?onboarding=owner`, { replace: true }) },
    )
  }

  return (
    <form onSubmit={submit} className="mx-auto flex min-h-dvh w-full max-w-[480px] flex-col bg-ink-50 px-4 pb-6 pt-4">
      <header className="mb-6 flex items-center gap-3">
        <Link to="/" aria-label="내 지도 목록으로" className="hit-44 flex size-8 items-center justify-center rounded-full bg-white shadow-float">
          <ChevronLeft size={20} />
        </Link>
        <h1 className="text-2xl font-bold text-ink-900">새 지도</h1>
      </header>

      <Field label="여행 제목">
        <TextField value={title} onChange={setTitle} maxLength={TITLE_MAX} placeholder="예: 부산 1박 2일" clearLabel="제목 지우기" />
      </Field>

      <Field as="div" label={<>지역 <span className="font-normal text-ink-500">(선택)</span></>}>
        <div className="field">
          <button type="button" onClick={() => setPickingRegion(true)} className="min-w-0 flex-1 text-left">
            {region ? region.label : <span className="text-ink-500">시·도 선택</span>}
          </button>
          {region ? (
            <ClearButton label="지역 지우기" onClick={() => setRegion(null)} />
          ) : (
            <ChevronDown size={16} className="text-ink-500" aria-hidden="true" />
          )}
        </div>
        <p className="mt-1.5 text-xs text-ink-500">고르면 그 지역 장소 정보를 미리 준비해요</p>
      </Field>

      <div className="grid grid-cols-2 gap-2">
        <Field label="시작일">
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="field w-full"
          />
        </Field>
        <Field label="종료일">
          <input
            type="date"
            value={endDate}
            min={startDate || undefined}
            onChange={(e) => setEndDate(e.target.value)}
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

      {create.error && <ErrorText message={createMapErrorMessage(create.error)} error={create.error} />}

      <button
        type="submit"
        disabled={!ready || create.isPending}
        className="btn-primary btn-lg mt-auto"
      >
        {create.isPending ? '만드는 중…' : '지도 만들기'}
      </button>

      {pickingRegion && (
        <RegionPicker
          value={region}
          onClose={() => setPickingRegion(false)}
          onDone={(next) => {
            setRegion(next)
            setPickingRegion(false)
          }}
        />
      )}
    </form>
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
