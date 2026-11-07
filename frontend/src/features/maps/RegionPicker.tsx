import { useState } from 'react'

import ModalSheet from '@/features/shell/ModalSheet'
import { josa } from '@/ui/josa'
import Sentences from '@/ui/Sentences'
import SheetTitle from '@/ui/SheetTitle'

import type { MapRegion } from './model'
import { AVAILABLE_REGIONS, REGION_SHORT, REGIONS } from './regions'

const open = REGIONS.filter((r) => r.label in AVAILABLE_REGIONS)
const beta = open.filter((r) => AVAILABLE_REGIONS[r.label].beta).map((r) => REGION_SHORT[r.label])
const soon = REGIONS.filter((r) => !(r.label in AVAILABLE_REGIONS)).map((r) => REGION_SHORT[r.label])

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
      {/* 고를 수 있는 곳만 같은 폭 칸(3열)으로 — 이름 길이가 달라 줄 끝이 들쭉날쭉하던 것을 맞춘다. 준비 중인 곳은 한 줄 글로. */}
      <div className="grid grid-cols-3 gap-2">
        {open.map((region) => {
          const on = picked?.label === region.label
          const { note, beta: isBeta } = AVAILABLE_REGIONS[region.label]
          // 칸에는 짧은 이름만 — 읽어 주는 이름은 정식 이름과 범위·베타까지.
          const name = [region.label, note, isBeta && '베타'].filter(Boolean).join(' ')
          return (
            <button key={region.label} type="button" aria-pressed={on} aria-label={name} onClick={() => setPicked(region)} className="chip w-full justify-center">
              {REGION_SHORT[region.label]}
              {note && <span className="text-xs">({note.replace(/만$/, '')})</span>}
            </button>
          )
        })}
      </div>
      {beta.length > 0 && (
        <p className="mt-3 text-xs text-ink-500">
          <Sentences text={`${beta.join(' · ')}${josa(beta[beta.length - 1], '은', '는')} 베타예요. 장소 정보가 아직 적을 수 있어요`} />
        </p>
      )}
      {/* 준비 중인 곳은 누를 수 없어 칸을 두지 않는다. 이름이 두 글자라 6열로 맞춰 줄 끝이 잘리지 않게 한다. */}
      {soon.length > 0 && (
        <div className="mt-4 text-xs text-ink-500">
          <p className="font-semibold text-ink-600">준비 중</p>
          <ul className="mt-1 grid grid-cols-6 gap-y-0.5">
            {soon.map((name) => (
              <li key={name}>{name}</li>
            ))}
          </ul>
        </div>
      )}
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
