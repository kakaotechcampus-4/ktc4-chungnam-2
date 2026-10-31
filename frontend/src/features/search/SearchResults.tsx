import { useState } from 'react'
import { ExternalLink } from 'lucide-react'

import { ApiError } from '@/api'
import ErrorText from '@/ErrorText'
import { useLivePlaceStore } from '@/features/map/livePlaces'
import { FILTER_CATEGORIES, type Pin, type PinCategory } from '@/features/map/model'
import { useCreatePinMutation } from '@/features/map/queries'
import { usePinSelection } from '@/features/map/usePinSelection'
import PanelBackLink from '@/features/shell/PanelBackLink'
import { showToast } from '@/features/shell/toast'
import EmptyState from '@/ui/EmptyState'
import { josa } from '@/ui/josa'
import SheetTitle from '@/ui/SheetTitle'
import TextField from '@/ui/TextField'

import { toSearchResult, type SearchResultView } from './model'
import { searchErrorMessage, useSourcePlacesQuery } from './queries'
import { useSearchStore } from './searchStore'

/**
 * 시트 제목 줄 — "'칼국수' 검색 결과 4곳" 또는 "링크에서 찾은 장소 1곳" + 닫기(잠깐 하는 작업이라 「닫기」, Figma 뒤로가기 규칙).
 * 붙여넣은 링크 원문은 길어서 제목에 싣지 않는다.
 */
export function SearchResultsHeader({ count }: { count: number | null }) {
  const { source, close } = useSearchStore()
  const n = count !== null ? ` ${count}곳` : ''
  return (
    <div className="flex items-center justify-between gap-2">
      {/* 링크에서 못 찾았으면 「0곳」 대신 이름을 묻거나 이름 검색을 권한다 — 제목은 링크의 장소로 둔다. */}
      <SheetTitle>{source?.kind === 'name' ? <>‘{source.query}’ 검색 결과{n}</> : count ? <>링크에서 찾은 장소{n}</> : '링크의 장소'}</SheetTitle>
      <button type="button" onClick={close} className="btn-text shrink-0 text-sm">
        닫기
      </button>
    </div>
  )
}

/** 검색 결과 목록·장소 상세(Figma 4절). 결과 0개는 0개로 보여준다(가드레일 2). */
export function SearchResultsBody({ mapId, pins }: { mapId: string; pins: Pin[] }) {
  const { source, near, selectedId, select, submit, close } = useSearchStore()
  const search = useSourcePlacesQuery(source, near)
  const create = useCreatePinMutation(mapId)
  const { selectPin } = usePinSelection()
  const results = (search.data?.places ?? []).map((r) => toSearchResult(r, near, pins))
  const link = search.data?.link
  const query = source?.kind === 'name' ? source.query : null
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

  /**
   * 자체 DB에 없는 장소를 실시간 핀으로 남긴다(#382). 서버에는 카카오 장소 ID·검색어·메모·분류만 보내고,
   * 이름·좌표는 보내지 않는다(저장 불가). 방금 찍은 핀의 위치는 이미 손에 있으니 바로 얹는다 — 메모리에만 둔다.
   */
  function pinLive(r: SearchResultView, { memo }: LiveInput) {
    const { place_id, lat, lng, category } = r.dto
    if (!category || !query) return
    create.mutate(
      { source: 'live', category, kakao_place_id: place_id, search_query: query, ...(memo ? { memo } : {}) },
      {
        onSuccess: (pin) => {
          useLivePlaceStore.getState().set(pin.id, { name: r.name, lat, lng })
          showToast(`${r.name}${josa(r.name, '을', '를')} 지도에 남겼어요`)
          close()
          selectPin(pin.id)
        },
        onError: (err) => showToast(pinErrorMessage(err)),
      },
    )
  }

  /**
   * 카카오 링크인데 자체 DB에 짝이 없다(#474 needs_search_query). 카카오 응답을 가져오지 않아 이름도 분류도 모르니
   * 사람이 이름(검색어)과 분류를 적는다. 서버에는 링크의 장소 ID·검색어·분류·메모만 보낸다. 위치는 지도를 열 때 검색어로 다시 찾는다.
   */
  function pinLinkLive(kakaoPlaceId: string, { memo, name, category }: LiveInput) {
    if (!name || !category) return
    create.mutate(
      { source: 'live', category, kakao_place_id: kakaoPlaceId, search_query: name, ...(memo ? { memo } : {}) },
      {
        onSuccess: (pin) => {
          showToast(`${name}${josa(name, '을', '를')} 지도에 남겼어요`)
          close()
          selectPin(pin.id)
        },
        onError: (err) => showToast(pinErrorMessage(err)),
      },
    )
  }

  if (search.isPending) return <p className="text-sm text-ink-500">찾는 중…</p>
  if (search.error) {
    return (
      <div className="space-y-3">
        <ErrorText message={searchErrorMessage(search.error)} error={search.error} />
        {source?.kind === 'link' && <SearchAgainButton onClose={close} label="이름으로 검색하기" />}
      </div>
    )
  }
  if (link && results.length === 0 && link.needs_search_query && link.kakao_place_id) {
    const kakaoPlaceId = link.kakao_place_id
    return <LiveLeaveForm askName pending={create.isPending} onSubmit={(input) => pinLinkLive(kakaoPlaceId, input)} />
  }
  if (link && results.length === 0) {
    const hint = link.name_hint
    return (
      <EmptyState
        mood="sorry"
        title="우리 장소 데이터에서 찾지 못했어요"
        action={
          hint ? (
            <button type="button" onClick={() => submit(hint, near)} className="btn-outline btn-md">
              링크 속 이름으로 찾아보기
            </button>
          ) : (
            <SearchAgainButton onClose={close} label="이름으로 검색하기" />
          )
        }
      >
        {/* 링크 속 이름은 사용자가 붙인 값이라 문장에 섞지 않고 따로 보여 준다(#717). */}
        {hint ? <q>{hint}</q> : '링크 대신 이름으로 찾아보세요'}
      </EmptyState>
    )
  }
  if (results.length === 0) {
    return (
      // 다음 행동을 하나 둔다 — 검색어를 지우고 바로 다시 입력하게(#351).
      <EmptyState mood="sorry"
        title="찾는 장소가 없어요"
        action={
          <SearchAgainButton onClose={close} label="검색어 지우고 다시 찾기" />
        }
      >
        이름을 짧게 줄여 보거나, 다른 이름으로 찾아보세요
      </EmptyState>
    )
  }

  if (selected) {
    return (
      <div className="space-y-3">
        <PanelBackLink label={`검색 결과 ${results.length}곳`} onBack={() => select(null)} />
        <div>
          <SheetTitle as="h3">{selected.name}</SheetTitle>
          <p className="text-body text-ink-600">{selected.meta}</p>
          {selected.far && <p className="text-body font-semibold text-warn-text">지금 보는 곳에서 멀어요 — 같은 이름의 다른 지역 가게일 수 있어요</p>}
        </div>
        {/* 카카오 검색은 사진·영업시간을 주지 않는다 — 사진 없이 카카오맵으로 보낸다(Figma 장소 정보 출처). */}
        {(selected.address || selected.url) && (
          <div className="space-y-2 rounded-xl bg-ink-50 p-3.5 text-body">
            {selected.address && <p className="text-ink-700">{selected.address}</p>}
            {selected.url && (
              <a href={selected.url} target="_blank" rel="noopener noreferrer" className="btn-link">
                카카오맵에서 자세히 보기 <ExternalLink size={14} aria-hidden="true" />
              </a>
            )}
          </div>
        )}
        {selected.canLeaveLive && !selected.alreadyPinned ? (
          <LiveLeaveForm pending={create.isPending} onSubmit={(input) => pinLive(selected, input)} />
        ) : (
          <PinItButton result={selected} filled pending={create.isPending} onPin={() => pinIt(selected)} />
        )}
      </div>
    )
  }

  return (
    <ol className="space-y-2">
      {results.map((r, i) => (
        <li
          key={r.id}
          className={`flex items-center gap-3 rounded-xl border p-3 ${r.unsupported && !r.canLeaveLive ? 'border-ink-200 opacity-60' : 'border-ink-200'}`}
        >
          <span className="flex size-6 shrink-0 items-center justify-center rounded-full border-2 border-brand-600 text-xs font-bold text-brand-600">
            {i + 1}
          </span>
          <button type="button" onClick={() => select(r.id)} className="min-w-0 flex-1 text-left">
            <p className="truncate font-bold text-ink-900">{r.name}</p>
            <p className="truncate text-xs text-ink-500">{r.meta}</p>
            {r.far && <p className="text-xs font-semibold text-warn-text">지금 보는 곳에서 멀어요</p>}
          </button>
          {r.canLeaveLive && !r.alreadyPinned ? (
            <button type="button" onClick={() => select(r.id)} className="btn-outline btn-sm">
              핀 남기기
            </button>
          ) : (
            <PinItButton result={r} pending={create.isPending && !!create.variables && 'place_id' in create.variables && create.variables.place_id === r.id} onPin={() => pinIt(r)} />
          )}
        </li>
      ))}
    </ol>
  )
}

/** 검색창을 비우고 다시 입력하게 한다(#351). */
function SearchAgainButton({ onClose, label }: { onClose: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={() => {
        onClose()
        document.getElementById('place-search')?.focus()
      }}
      className="btn-outline btn-md"
    >
      {label}
    </button>
  )
}

const MEMO_MAX = 200
const NAME_MAX = 100

type LiveInput = { memo: string; name?: string; category?: PinCategory }

/**
 * 자체 DB에 없는 장소 — 장소 정보·AI 추천·동선에는 못 쓰지만 핀으로 남겨 의견을 나눌 수 있다(#382). 메모는 선택이다.
 * `askName`이면(카카오 링크, #487) 이름과 분류도 받는다 — 지도를 열 때 그 이름으로 카카오에서 위치를 다시 찾는다.
 */
function LiveLeaveForm({ askName = false, pending, onSubmit }: { askName?: boolean; pending: boolean; onSubmit: (input: LiveInput) => void }) {
  const [memo, setMemo] = useState('')
  const [name, setName] = useState('')
  const [category, setCategory] = useState<PinCategory | null>(null)
  const ready = !askName || (name.trim() !== '' && category !== null)
  return (
    <div className="space-y-2.5">
      <div className="rounded-xl bg-ink-50 p-3.5 text-body text-ink-700">
        <p className="font-semibold text-ink-900">우리 장소 데이터에 없는 곳이에요</p>
        <p className="mt-0.5">장소 정보와 조건 확인, AI 추천, 동선에는 쓰이지 않아요. 그래도 핀으로 남겨서 서로 의견을 나눌 수 있어요.</p>
      </div>
      {askName && (
        <>
          <label className="block space-y-1.5">
            <span className="block text-body font-bold text-ink-900">장소 이름</span>
            <TextField value={name} onChange={setName} maxLength={NAME_MAX} placeholder="카카오맵에 나온 이름 그대로" clearLabel="이름 지우기" />
          </label>
          <p className="text-xs text-ink-500">지도를 열 때 이 이름으로 카카오맵에서 위치를 찾아요</p>
          <div role="group" aria-label="분류" className="flex flex-wrap gap-2">
            {FILTER_CATEGORIES.map((c) => (
              <button key={c} type="button" aria-pressed={category === c} onClick={() => setCategory(c)} className="chip">
                {c}
              </button>
            ))}
          </div>
        </>
      )}
      <label className="block text-body font-bold text-ink-900" htmlFor="live-pin-memo">
        한마디 남기기 (선택)
      </label>
      <textarea
        id="live-pin-memo"
        value={memo}
        maxLength={MEMO_MAX}
        onChange={(e) => setMemo(e.target.value)}
        placeholder="예: 여기 곱창 맛있대"
        rows={2}
        className="field w-full resize-none py-3"
      />
      <p className="text-right text-label text-ink-500">
        {memo.length}/{MEMO_MAX}
      </p>
      <button
        type="button"
        onClick={() => onSubmit({ memo: memo.trim(), name: name.trim() || undefined, category: category ?? undefined })}
        disabled={pending || !ready}
        className="btn-primary btn-lg w-full"
      >
        {pending ? '남기는 중…' : '그래도 핀 남기기'}
      </button>
    </div>
  )
}

/** 상세에선 이 화면의 유일한 채움 버튼, 목록에선 외곽선. 찍을 수 없으면 버튼 대신 이유를 적는다. */
function PinItButton({ result, filled = false, pending, onPin }: { result: SearchResultView; filled?: boolean; pending: boolean; onPin: () => void }) {
  if (result.alreadyPinned) return <span className="shrink-0 text-xs text-ink-500">이미 지도에 있어요</span>
  if (result.unsupported) {
    return <span className="shrink-0 text-xs text-ink-500">{result.dto.category ? '핀으로 남길 수 없는 분류예요' : '분류를 알 수 없는 장소예요'}</span>
  }
  return (
    <button
      type="button"
      onClick={onPin}
      disabled={pending}
      className={
        filled ? 'btn-primary btn-lg w-full' : 'btn-outline btn-sm'
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
