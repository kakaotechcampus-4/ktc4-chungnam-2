import { useState } from 'react'

import ModalSheet from '@/features/shell/ModalSheet'

import type { MapRegion } from './model'
import { REGIONS } from './regions'

/** 지도 만들기의 시·도 고르기(Figma 1절 '지역 선택'). 고르기 전까지는 확정 버튼이 꺼져 있다. */
export default function RegionPicker({
  value,
  onDone,
  onClose,
}: {
  value: MapRegion | null
  onDone: (region: MapRegion | null) => void
  onClose: () => void
}) {
  const [picked, setPicked] = useState(value)

  return (
    <ModalSheet label="여행 지역 고르기" onClose={onClose}>
      <h2 className="text-lg font-bold text-ink-900">여행 지역 (시·도)</h2>
      <p className="mb-4 mt-1 text-sm text-ink-500">고르면 그 지역 장소 정보를 미리 준비해요</p>
      <div className="flex flex-wrap gap-2">
        {REGIONS.map((region) => {
          const on = picked?.label === region.label
          return (
            <button
              key={region.label}
              type="button"
              aria-pressed={on}
              onClick={() => setPicked(region)}
              className={`rounded-full border px-3 py-1.5 text-sm ${
                on ? 'border-brand-600 bg-brand-100 font-semibold text-brand-700' : 'border-ink-300 text-ink-700'
              }`}
            >
              {region.label}
            </button>
          )
        })}
      </div>
      <div className="mt-6 grid grid-cols-[1fr_2fr] gap-2">
        <button type="button" onClick={() => onDone(null)} className="rounded-xl border border-ink-300 py-3 text-sm">
          선택 안 함
        </button>
        <button
          type="button"
          disabled={!picked}
          onClick={() => onDone(picked)}
          className="rounded-xl bg-brand-600 py-3 text-sm font-semibold text-white disabled:bg-ink-100 disabled:text-ink-400"
        >
          {picked ? `${picked.label}로 정하기` : '지역을 골라 주세요'}
        </button>
      </div>
    </ModalSheet>
  )
}
