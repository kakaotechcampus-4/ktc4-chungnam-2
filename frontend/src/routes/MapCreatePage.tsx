import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { ChevronDown, ChevronLeft, X } from 'lucide-react'

import ErrorText from '@/ErrorText'
import type { MapRegion } from '@/features/maps/model'
import { useCreateMapMutation } from '@/features/maps/queries'
import RegionPicker from '@/features/maps/RegionPicker'

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
    <form onSubmit={submit} className="flex min-h-dvh flex-col bg-ink-50 px-4 pb-6 pt-4">
      <header className="mb-6 flex items-center gap-3">
        <Link to="/" aria-label="내 지도 목록으로" className="flex size-8 items-center justify-center rounded-full bg-white shadow-sm">
          <ChevronLeft size={20} />
        </Link>
        <h1 className="text-2xl font-bold text-ink-900">새 지도</h1>
      </header>

      <Field label="여행 제목">
        <div className="flex items-center gap-2 rounded-xl border border-ink-300 bg-white px-3 py-3 focus-within:border-brand-600">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={TITLE_MAX}
            placeholder="예: 부산 1박 2일"
            className="min-w-0 flex-1 bg-transparent outline-none"
          />
          {title && <ClearButton label="제목 지우기" onClick={() => setTitle('')} />}
          {title && <span className="text-xs text-ink-400">{title.length}/{TITLE_MAX}</span>}
        </div>
      </Field>

      <Field as="div" label={<>지역 <span className="font-normal text-ink-400">(선택)</span></>}>
        <div className="flex items-center gap-2 rounded-xl border border-ink-300 bg-white px-3 py-3">
          <button type="button" onClick={() => setPickingRegion(true)} className="min-w-0 flex-1 text-left">
            {region ? region.label : <span className="text-ink-400">시·도 선택</span>}
          </button>
          {region ? (
            <ClearButton label="지역 지우기" onClick={() => setRegion(null)} />
          ) : (
            <ChevronDown size={18} className="text-ink-400" aria-hidden="true" />
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
            className="w-full rounded-xl border border-ink-300 bg-white px-3 py-3"
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
            className={`w-full rounded-xl border bg-white px-3 py-3 ${dateError ? 'border-[var(--warn-line)]' : 'border-ink-300'}`}
          />
        </Field>
      </div>
      {dateError && (
        <p id="date-error" className="-mt-2 text-sm text-[var(--warn-text)]">
          종료일은 시작일과 같거나 뒤여야 해요
        </p>
      )}

      {create.error && <ErrorText message="지도를 만들지 못했어요" error={create.error} />}

      <button
        type="submit"
        disabled={!ready || create.isPending}
        className="mt-auto rounded-xl bg-brand-600 py-3.5 font-semibold text-white disabled:bg-ink-100 disabled:text-ink-400"
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

/** 입력칸에 글자가 있을 때만 붙는 ✕(Figma 규칙). */
function ClearButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className="flex size-5 shrink-0 items-center justify-center rounded-full bg-ink-300 text-white"
    >
      <X size={12} />
    </button>
  )
}
