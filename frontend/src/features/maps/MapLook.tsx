import { useEffect, useId, useMemo, useState } from 'react'
import { Check } from 'lucide-react'

import { apiUrl, ApiError } from '@/api'
import ErrorText from '@/ErrorText'
import ModalSheet from '@/features/shell/ModalSheet'
import { showToast } from '@/features/shell/toast'
import RegionCover from '@/ui/RegionCover'
import SheetTitle from '@/ui/SheetTitle'
import Sentences from '@/ui/Sentences'
import BusyLabel from '@/ui/BusyLabel'

import { cardTint, MAP_COLORS, shrinkImage } from './look'
import type { MapView } from './model'
import { useCoverMutation, useUpdateMapMutation } from './queries'

/** 카드·편집 창 위의 대표 이미지 — 올린 이미지가 있으면 그것, 없으면 지역 기본 그림(#1445). 장식이라 숨긴다. */
export function MapCover({ map, className = '' }: { map: Pick<MapView, 'region' | 'coverUrl'>; className?: string }) {
  if (map.coverUrl) return <CoverImage key={map.coverUrl} src={apiUrl(map.coverUrl)} className={className} />
  return <RegionCover region={map.region} className={className} />
}

/**
 * 올린 사진 — 받기 전에는 회색 면, 받으면 흐릿한 데서 선명해지며 나타난다(#1675, 로딩 패턴 「블러 업」).
 * 빈 칸이었다가 사진이 툭 나타나던 것을 바꿨다. 작은 미리보기 사진은 서버에 없어서 흐림은 받은 사진에 건다.
 * 캐시에서 바로 온 사진은 onLoad 전에 이미 다 받았을 수 있어 ref 에서도 본다. 동작 줄이기면 바로 보인다.
 */
function CoverImage({ src, className }: { src: string; className: string }) {
  const [loaded, setLoaded] = useState(false)
  return (
    <span className={`overflow-hidden bg-ink-100 ${className}`}>
      <img
        src={src}
        alt=""
        ref={(el) => {
          if (el?.complete && el.naturalWidth > 0) setLoaded(true)
        }}
        onLoad={() => setLoaded(true)}
        className={`h-full w-full object-cover transition-[opacity,filter] duration-500 motion-reduce:transition-none ${loaded ? 'opacity-100 blur-0' : 'opacity-0 blur-md'}`}
      />
    </span>
  )
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
 * 대표 이미지 편집(방장만, #1445). 사진을 고르면 브라우저에서 줄여 미리보기에만 보이고, 「저장」을 눌러야 올린다(#1643).
 * 「기본 그림으로」도 미리보기만 지역 명소 그림으로 바꾼다. 「닫기」는 고른 것을 버린다.
 */
export function CoverSheet({ map, onClose }: { map: MapView; onClose: () => void }) {
  const cover = useCoverMutation(map.id)
  const [shrinkFailed, setShrinkFailed] = useState(false)
  // undefined = 고친 것 없음, null = 기본 그림으로, Blob = 고른 사진
  const [draft, setDraft] = useState<Blob | null | undefined>(undefined)
  const preview = useMemo(() => (draft ? URL.createObjectURL(draft) : null), [draft])
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview) }, [preview])
  const inputId = useId()
  const showsUpload = draft === undefined ? Boolean(map.coverUrl) : draft !== null

  async function pick(file: File | undefined) {
    if (!file) return
    setShrinkFailed(false)
    const limit = cover.error instanceof ApiError ? Number(cover.error.detail?.limit_bytes) || undefined : undefined
    try {
      setDraft(await shrinkImage(file, limit))
    } catch {
      setShrinkFailed(true)
    }
  }

  function save() {
    if (draft === undefined) return
    cover.mutate(draft, {
      onSuccess: () => {
        showToast(draft ? '대표 이미지를 바꿨어요' : '기본 그림으로 바꿨어요')
        onClose()
      },
    })
  }

  return (
    <ModalSheet label="대표 이미지 편집" onClose={onClose}>
      <SheetTitle>대표 이미지 편집</SheetTitle>
      <p className="mt-1 text-sm text-ink-600"><Sentences text="구성원과 초대 링크를 받은 사람에게 보여요. 카톡 미리보기에도 나와요" /></p>
      <div className="mt-4 overflow-hidden rounded-xl border border-ink-200">
        {preview ? (
          <img src={preview} alt="" className="block aspect-[16/7] w-full object-cover" />
        ) : (
          <MapCover map={draft === null ? { region: map.region } : map} className="block aspect-[16/7] w-full" />
        )}
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
        <label htmlFor={inputId} className={`btn-outline btn-lg w-full ${cover.isPending ? 'pointer-events-none opacity-60' : 'cursor-pointer'}`}>
          사진 고르기
        </label>
        {showsUpload && (
          <button type="button" disabled={cover.isPending} onClick={() => setDraft(null)} className="btn-outline btn-lg w-full">
            기본 그림으로
          </button>
        )}
        <div className="grid grid-cols-2 gap-2 pt-2">
          <button type="button" onClick={onClose} className="btn-neutral btn-lg">
            닫기
          </button>
          <button type="button" disabled={draft === undefined || cover.isPending} onClick={save} aria-busy={cover.isPending} className="btn-primary btn-lg">
            <BusyLabel busy={cover.isPending} busyText="저장하는 중…">저장</BusyLabel>
          </button>
        </div>
      </div>
    </ModalSheet>
  )
}

/**
 * 지도 색 변경(방장만, #1445). 파스텔 견본 8개 + 직접 고르기(브라우저 색 고르기 창) + 색 없음.
 * 견본·직접 고르기·「색 없음」은 미리보기 카드만 바꾸고, 맨 아래 「저장」이 저장하고 창을 닫는다(#1643).
 * 「닫기」는 고른 색을 버린다. 대표 이미지 창과 같은 방식이다.
 * 색은 목록 카드 바탕에만 쓴다(#1537) — 미리보기도 목록 카드 모양 그대로 보여 준다.
 */
export function ColorSheet({ map, onClose }: { map: MapView; onClose: () => void }) {
  const update = useUpdateMapMutation(map.id)
  const [color, setColor] = useState<string | null>(map.color ?? null)
  const custom = color != null && !MAP_COLORS.some((c) => c.value.toLowerCase() === color.toLowerCase())

  const changed = (color?.toLowerCase() ?? null) !== (map.color?.toLowerCase() ?? null)

  function save() {
    update.mutate(
      { color },
      {
        onSuccess: () => {
          showToast(color ? '지도 색을 바꿨어요' : '지도 색을 지웠어요')
          onClose()
        },
      },
    )
  }

  const swatch = 'relative flex size-11 items-center justify-center rounded-full border border-ink-300'
  return (
    <ModalSheet label="색상 변경" onClose={onClose}>
      <SheetTitle>색상 변경</SheetTitle>
      <p className="mt-1 text-sm text-ink-600"><Sentences text="내 지도 목록의 카드 바탕 색이에요. 구성원 모두에게 같은 색이 보여요" /></p>
      {/* 목록 카드(MapListPage)와 같은 모양이다. 고른 색이 없으면 흰 카드다. */}
      <div aria-hidden="true" style={color ? cardTint(color) : undefined} className="mt-4 overflow-hidden rounded-xl border border-ink-200 bg-surface">
        <MapCover map={map} className="block aspect-[16/6] w-full" />
        <div className="p-4">
          <p className="truncate text-title font-bold text-ink-900">{map.title}</p>
          <p className="mt-1 text-sm text-ink-600">{map.summary}</p>
        </div>
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
              onClick={() => setColor(c.value)}
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
        {color && (
          <button type="button" disabled={update.isPending} onClick={() => setColor(null)} className="btn-outline btn-lg w-full">
            색 없음
          </button>
        )}
        <div className="grid grid-cols-2 gap-2 pt-2">
          <button type="button" onClick={onClose} className="btn-neutral btn-lg">
            닫기
          </button>
          <button type="button" disabled={!changed || update.isPending} onClick={save} aria-busy={update.isPending} className="btn-primary btn-lg">
            <BusyLabel busy={update.isPending} busyText="저장하는 중…">저장</BusyLabel>
          </button>
        </div>
      </div>
    </ModalSheet>
  )
}
