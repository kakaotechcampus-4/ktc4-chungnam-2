import { useState } from 'react'

import ModalSheet from '@/features/shell/ModalSheet'
import SheetTitle from '@/ui/SheetTitle'

import type { MapRegion } from './model'
import { AVAILABLE_REGIONS, REGIONS } from './regions'

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
      <SheetTitle>여행 지역 (시·도)</SheetTitle>
      <p className="mb-4 mt-1 text-sm text-ink-500">고르면 그 지역 장소 정보를 미리 준비해요</p>
      <div className="flex flex-wrap gap-2">
        {REGIONS.map((region) => {
          const on = picked?.label === region.label
          const open = region.label in AVAILABLE_REGIONS
          const { note, beta } = AVAILABLE_REGIONS[region.label] ?? {}
          return (
            <button
              key={region.label}
              type="button"
              aria-pressed={on}
              disabled={!open}
              onClick={() => setPicked(region)}
              className="chip"
            >
              {region.label}
              {note && <span className="ml-1 text-xs">· {note}</span>}
              {beta && <span className="ml-1 text-xs">(베타)</span>}
              {!open && <span className="ml-1 text-xs">· 준비 중</span>}
            </button>
          )
        })}
      </div>
      <p className="mt-3 text-xs text-ink-500">(베타) 지역은 장소 정보가 아직 적을 수 있어요</p>
      <div className="mt-6 grid grid-cols-[1fr_2fr] gap-2">
        <button type="button" onClick={() => onDone(null)} className="btn-neutral btn-lg">
          선택 안 함
        </button>
        <button
          type="button"
          disabled={!picked}
          onClick={() => onDone(picked)}
          className="btn-primary btn-lg"
        >
          {picked ? `${picked.label}로 정하기` : '지역을 골라 주세요'}
        </button>
      </div>
    </ModalSheet>
  )
}
