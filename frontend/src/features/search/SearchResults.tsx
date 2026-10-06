import { ExternalLink } from 'lucide-react'

import { ApiError } from '@/api'
import ErrorText from '@/ErrorText'
import type { Pin } from '@/features/map/model'
import { useCreatePinMutation } from '@/features/map/queries'
import { usePinSelection } from '@/features/map/usePinSelection'
import { showToast } from '@/features/shell/toast'
import { josa } from '@/ui/josa'

import { toSearchResult, type SearchResultView } from './model'
import { searchErrorMessage, usePlaceSearchQuery } from './queries'
import { useSearchStore } from './searchStore'

/** 시트 제목 줄 — "'칼국수' 검색 결과 4곳" + 닫기(잠깐 하는 작업이라 「닫기」, Figma 뒤로가기 규칙). */
export function SearchResultsHeader({ count }: { count: number | null }) {
  const { query, close } = useSearchStore()
  return (
    <div className="flex items-center justify-between gap-2">
      <h2 className="truncate text-lg font-bold text-ink-900">
        ‘{query}’ 검색 결과{count !== null && ` ${count}곳`}
      </h2>
      <button type="button" onClick={close} className="hit-44 shrink-0 text-sm text-ink-500">
        닫기
      </button>
    </div>
  )
}

/** 검색 결과 목록·장소 상세(Figma 4절). 결과 0개는 0개로 보여준다(가드레일 2). */
export function SearchResultsBody({ mapId, pins }: { mapId: string; pins: Pin[] }) {
  const { query, near, selectedId, select, close } = useSearchStore()
  const search = usePlaceSearchQuery(query, near)
  const create = useCreatePinMutation(mapId)
  const { selectPin } = usePinSelection()
  const results = (search.data ?? []).map((r) => toSearchResult(r, near, pins))
  const selected = results.find((r) => r.id === selectedId)

  function pinIt(r: SearchResultView) {
    const { place_id, place_name, lat, lng, category } = r.dto
    if (!category) return
    // 검색 결과는 매칭 힌트로 그대로 되돌려 보낸다 — 서버가 같은 자체 DB 장소를 찾는다(#191).
    create.mutate(
      { source: 'search', place_id, place_name, lat, lng, category },
      {
        onSuccess: (pin) => {
          const name = pin.place_name ?? place_name
          showToast(`${name}${josa(name, '을', '를')} 지도에 찍었어요`)
          close()
          // 새 핀은 0표라 목록 끝으로 간다. 다음 할 일은 그 핀에 의견 남기기라 바로 상세를 연다(#308).
          if (pin.id) selectPin(pin.id)
        },
        onError: (err) => showToast(pinErrorMessage(err)),
      },
    )
  }

  if (search.isPending) return <p className="text-sm text-ink-500">찾는 중…</p>
  if (search.error) return <ErrorText message={searchErrorMessage(search.error)} error={search.error} />
  if (results.length === 0) {
    return (
      <div className="py-8 text-center">
        <p className="font-semibold text-ink-900">찾는 장소가 없어요</p>
        <p className="mt-1 text-sm text-ink-500">이름을 짧게 줄여 보거나, 다른 이름으로 찾아보세요</p>
        {/* 다음 행동을 하나 둔다 — 검색어를 지우고 바로 다시 입력하게(#351). */}
        <button
          type="button"
          onClick={() => {
            close()
            document.getElementById('place-search')?.focus()
          }}
          className="btn-outline mt-4 px-4 py-2.5 text-sm"
        >
          검색어 지우고 다시 찾기
        </button>
      </div>
    )
  }

  if (selected) {
    return (
      <div className="space-y-3">
        <button type="button" onClick={() => select(null)} className="hit-44 text-[0.8125rem] font-medium text-ink-500">
          ‹ 검색 결과 {results.length}곳
        </button>
        <div>
          <h3 className="text-[1.375rem] font-bold text-ink-900">{selected.name}</h3>
          <p className="text-[0.8125rem] text-ink-600">{selected.meta}</p>
          {selected.far && <p className="text-[0.8125rem] font-semibold text-warn-text">지금 보는 곳에서 멀어요 — 같은 이름의 다른 지역 가게일 수 있어요</p>}
        </div>
        {/* 카카오 검색은 사진·영업시간을 주지 않는다 — 사진 없이 카카오맵으로 보낸다(Figma 장소 정보 출처). */}
        {(selected.address || selected.url) && (
          <div className="space-y-2 rounded-xl bg-ink-50 p-3.5 text-[0.8125rem]">
            {selected.address && <p className="text-ink-700">{selected.address}</p>}
            {selected.url && (
              <a href={selected.url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 font-bold text-brand-600">
                카카오맵에서 자세히 보기 <ExternalLink size={14} aria-hidden="true" />
              </a>
            )}
          </div>
        )}
        <PinItButton result={selected} filled pending={create.isPending} onPin={() => pinIt(selected)} />
      </div>
    )
  }

  return (
    <ol className="space-y-2">
      {results.map((r, i) => (
        <li
          key={r.id}
          className={`flex items-center gap-3 rounded-xl border p-3 ${r.unsupported ? 'border-ink-200 opacity-60' : 'border-ink-200'}`}
        >
          <span className="flex size-6 shrink-0 items-center justify-center rounded-full border-2 border-brand-600 text-xs font-bold text-brand-600">
            {i + 1}
          </span>
          <button type="button" onClick={() => select(r.id)} className="min-w-0 flex-1 text-left">
            <p className="truncate font-bold text-ink-900">{r.name}</p>
            <p className="truncate text-xs text-ink-500">{r.meta}</p>
            {r.far && <p className="text-xs font-semibold text-warn-text">지금 보는 곳에서 멀어요</p>}
          </button>
          <PinItButton result={r} pending={create.isPending && create.variables?.place_id === r.id} onPin={() => pinIt(r)} />
        </li>
      ))}
    </ol>
  )
}

/** 상세에선 이 화면의 유일한 채움 버튼, 목록에선 외곽선. 찍을 수 없으면 버튼 대신 이유를 적는다. */
function PinItButton({ result, filled = false, pending, onPin }: { result: SearchResultView; filled?: boolean; pending: boolean; onPin: () => void }) {
  if (result.alreadyPinned) return <span className="shrink-0 text-xs text-ink-500">이미 지도에 있어요</span>
  if (result.unsupported) return <span className="shrink-0 text-xs text-ink-500">아직 지원하지 않는 장소예요</span>
  return (
    <button
      type="button"
      onClick={onPin}
      disabled={pending}
      className={
        filled
          ? 'btn-primary w-full py-3'
          : 'btn-outline shrink-0 px-3 py-1.5 text-sm'
      }
    >
      {pending ? '찍는 중…' : '핀 찍기'}
    </button>
  )
}

/** docs/errors.md — 핀 만들기 실패. */
function pinErrorMessage(err: unknown): string {
  if (err instanceof ApiError && err.code === 'PIN_DUPLICATE') return '이미 지도에 있는 장소예요'
  if (err instanceof ApiError && err.code === 'PLACE_NOT_SUPPORTED') return '아직 지원하지 않는 장소예요'
  return '핀을 찍지 못했어요'
}
