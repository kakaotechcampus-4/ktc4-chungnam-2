import { useId, useState } from 'react'
import { Check } from 'lucide-react'

import { apiUrl, ApiError } from '@/api'
import ErrorText from '@/ErrorText'
import ModalSheet from '@/features/shell/ModalSheet'
import { showToast } from '@/features/shell/toast'
import RegionCover from '@/ui/RegionCover'
import SheetTitle from '@/ui/SheetTitle'

import { MAP_COLORS, shrinkImage } from './look'
import type { MapView } from './model'
import { useCoverMutation, useUpdateMapMutation } from './queries'

/** 카드·편집 창 위의 대표 이미지 — 올린 이미지가 있으면 그것, 없으면 지역 기본 그림(#1445). 장식이라 숨긴다. */
export function MapCover({ map, className = '' }: { map: Pick<MapView, 'region' | 'color' | 'coverUrl'>; className?: string }) {
  if (map.coverUrl) {
    return <img src={apiUrl(map.coverUrl)} alt="" className={`object-cover ${className}`} />
  }
  return <RegionCover region={map.region} color={map.color} className={className} />
}

/** 서버가 막은 이유. 크기 상한은 응답의 detail.limit_bytes 로 적는다(화면에 숫자를 두지 않는다). */
function coverErrorMessage(err: unknown): string {
  if (err instanceof ApiError && err.code === 'COVER_INVALID') {
    const limit = Number(err.detail?.limit_bytes)
    return limit ? `사진이 너무 커요. ${Math.floor(limit / 1024)}KB 이하로 올려 주세요` : '이 사진은 올릴 수 없어요'
  }
  return '대표 이미지를 바꾸지 못했어요'
}

/**
 * 대표 이미지 편집(방장만, #1445). 사진을 고르면 브라우저에서 줄여 바로 올린다. 올린 이미지가 있으면
 * 「기본 그림으로」가 지역 명소 그림으로 되돌린다.
 */
export function CoverSheet({ map, onClose }: { map: MapView; onClose: () => void }) {
  const cover = useCoverMutation(map.id)
  const [shrinkFailed, setShrinkFailed] = useState(false)
  const inputId = useId()

  async function pick(file: File | undefined) {
    if (!file) return
    setShrinkFailed(false)
    const limit = cover.error instanceof ApiError ? Number(cover.error.detail?.limit_bytes) || undefined : undefined
    let image: Blob
    try {
      image = await shrinkImage(file, limit)
    } catch {
      setShrinkFailed(true)
      return
    }
    cover.mutate(image, { onSuccess: () => showToast('대표 이미지를 바꿨어요') })
  }

  return (
    <ModalSheet label="대표 이미지 편집" onClose={onClose}>
      <SheetTitle>대표 이미지 편집</SheetTitle>
      <p className="mt-1 text-sm text-ink-600">구성원 모두에게 같은 이미지가 보여요</p>
      <div className="mt-4 overflow-hidden rounded-xl border border-ink-200">
        <MapCover map={map} className="block aspect-[16/7] w-full" />
      </div>
      {shrinkFailed && <ErrorText message="이 사진은 열 수 없어요. 다른 사진을 골라 주세요" error={null} />}
      {cover.error && <ErrorText message={coverErrorMessage(cover.error)} error={cover.error} />}
      <div className="mt-5 space-y-2">
        {/* 파일 고르기 창은 input 이 연다. 보이는 버튼은 그 input 의 label 이다. */}
        <input
          id={inputId}
          type="file"
          accept="image/*"
          className="sr-only"
          disabled={cover.isPending}
          onChange={(e) => {
            void pick(e.target.files?.[0])
            e.target.value = ''
          }}
        />
        <label htmlFor={inputId} className={`btn-primary btn-lg w-full ${cover.isPending ? 'pointer-events-none opacity-60' : 'cursor-pointer'}`}>
          {cover.isPending ? '올리는 중…' : '사진 고르기'}
        </label>
        {map.coverUrl && (
          <button
            type="button"
            disabled={cover.isPending}
            onClick={() => cover.mutate(null, { onSuccess: () => showToast('기본 그림으로 바꿨어요') })}
            className="btn-outline btn-lg w-full"
          >
            기본 그림으로
          </button>
        )}
        <button type="button" onClick={onClose} className="btn-neutral btn-lg w-full">
          닫기
        </button>
      </div>
    </ModalSheet>
  )
}

/**
 * 지도 색 변경(방장만, #1445). 파스텔 견본 8개 + 직접 고르기(브라우저 색 고르기 창) + 색 없음.
 * 견본은 누르는 즉시 저장하고, 직접 고른 색은 「이 색으로 저장」으로 저장한다. 미리보기는 위 그림이 바로 보여 준다.
 */
export function ColorSheet({ map, onClose }: { map: MapView; onClose: () => void }) {
  const update = useUpdateMapMutation(map.id)
  const [color, setColor] = useState<string | null>(map.color ?? null)
  const custom = color != null && !MAP_COLORS.some((c) => c.value.toLowerCase() === color.toLowerCase())

  function save(next: string | null) {
    setColor(next)
    update.mutate({ color: next }, { onSuccess: () => showToast(next ? '지도 색을 바꿨어요' : '지도 색을 지웠어요') })
  }

  const swatch = 'relative flex size-11 items-center justify-center rounded-full border border-ink-300'
  return (
    <ModalSheet label="색상 변경" onClose={onClose}>
      <SheetTitle>색상 변경</SheetTitle>
      <p className="mt-1 text-sm text-ink-600">목록 카드 바탕과 기본 그림의 하늘 색이에요</p>
      <div className="mt-4 overflow-hidden rounded-xl border border-ink-200">
        <MapCover map={{ ...map, color: color ?? undefined }} className="block aspect-[16/7] w-full" />
      </div>
      <div role="radiogroup" aria-label="지도 색" className="mt-4 flex flex-wrap gap-3">
        {MAP_COLORS.map((c) => {
          const on = color?.toLowerCase() === c.value.toLowerCase()
          return (
            <button
              key={c.value}
              type="button"
              role="radio"
              aria-checked={on}
              aria-label={c.name}
              disabled={update.isPending}
              onClick={() => save(c.value)}
              className={`${swatch} ${on ? 'ring-2 ring-brand-600 ring-offset-2' : ''}`}
              style={{ background: c.value }}
            >
              {on && <Check size={18} className="text-ink-900" aria-hidden="true" />}
            </button>
          )
        })}
        {/* 직접 고르기 — 브라우저의 색 고르기 창. 고른 색이 견본에 없으면 이 칸이 켜진다. */}
        <label
          className={`${swatch} cursor-pointer overflow-hidden ${custom ? 'ring-2 ring-brand-600 ring-offset-2' : ''}`}
          style={{ background: custom ? color : 'conic-gradient(#FDE2E4, #FFF1C9, #DCEFE3, #DDE7FB, #EADCF8, #FDE2E4)' }}
        >
          <span className="sr-only">직접 고르기</span>
          <input
            type="color"
            value={custom ? color : '#ffffff'}
            disabled={update.isPending}
            onChange={(e) => setColor(e.target.value)}
            className="absolute inset-0 size-full cursor-pointer opacity-0"
          />
          {custom && <Check size={18} className="text-ink-900" aria-hidden="true" />}
        </label>
      </div>
      {update.error && <ErrorText message="지도 색을 바꾸지 못했어요" error={update.error} />}
      <div className="mt-5 space-y-2">
        {/* 직접 고른 색은 고르기 창을 움직이는 동안 계속 바뀌어서, 다 고른 뒤 이 버튼으로 저장한다. */}
        {custom && color !== map.color && (
          <button type="button" disabled={update.isPending} onClick={() => save(color)} className="btn-primary btn-lg w-full">
            이 색으로 저장
          </button>
        )}
        {map.color && (
          <button type="button" disabled={update.isPending} onClick={() => save(null)} className="btn-outline btn-lg w-full">
            색 없음
          </button>
        )}
        <button type="button" onClick={onClose} className="btn-neutral btn-lg w-full">
          닫기
        </button>
      </div>
    </ModalSheet>
  )
}
