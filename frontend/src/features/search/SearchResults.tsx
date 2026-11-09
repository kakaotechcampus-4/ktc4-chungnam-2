import { useState } from 'react'
import { ExternalLink } from 'lucide-react'

import ErrorText from '@/ErrorText'
import { useLivePlaceStore } from '@/features/map/livePlaces'
import { FILTER_CATEGORIES, inputExample, type Pin, type PinCategory } from '@/features/map/model'
import { useCreatePinMutation } from '@/features/map/queries'
import { usePinSelection } from '@/features/map/usePinSelection'
import PanelBackLink from '@/features/shell/PanelBackLink'
import { showToast } from '@/features/shell/toast'
import BlogPhotos from '@/ui/BlogPhotos'
import CardSkeleton from '@/ui/CardSkeleton'
import EmptyState from '@/ui/EmptyState'
import ExternalSearchLink from '@/ui/ExternalSearchLink'
import { josa } from '@/ui/josa'
import SheetTitle from '@/ui/SheetTitle'
import TextField from '@/ui/TextField'
import TextArea from '@/ui/TextArea'
import Sentences from '@/ui/Sentences'

import { livePinRequest, pinErrorMessage, searchPinRequest, toSearchResult, type SearchResultView } from './model'
import { searchErrorMessage, useExternalSearchQuery, usePlacePhotosQuery, useSourcePlacesQuery } from './queries'
import { useSearchStore } from './searchStore'
import { suggestQuery } from './typo'

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
      <SheetTitle>
        {source?.kind === 'name' ? (
          <>‘{source.query}’ 검색 결과{n}</>
        ) : source?.kind === 'tap' ? (
          <>누른 곳 근처 장소{n}</>
        ) : count ? (
          <>링크에서 찾은 장소{n}</>
        ) : (
          '링크의 장소'
        )}
      </SheetTitle>
      <button type="button" onClick={close} className="btn-text shrink-0 text-sm">
        닫기
      </button>
    </div>
  )
}

/** 검색 결과 목록·장소 상세(Figma 4절). 결과 0개는 0개로 보여준다(가드레일 2). */
export function SearchResultsBody({ mapId, pins }: { mapId: string; pins: Pin[] }) {
  const { source, near, selectedId, group, select, showGroup, submit, close } = useSearchStore()
  const search = useSourcePlacesQuery(source, near)
  const create = useCreatePinMutation(mapId)
  const { selectPin } = usePinSelection()
  const results = (search.data?.places ?? []).map((r) => toSearchResult(r, near, pins))
  // 지도 자리 메뉴에서만 온다 — 자체 DB에 없는 근처 가게(카카오), 실시간 핀으로 남긴다(#1549).
  const nearby = (search.data?.nearby ?? []).map((r) => toSearchResult(r, near, pins))
  const link = search.data?.link
  const query = source?.kind === 'name' ? source.query : null
  const selected = [...results, ...nearby].find((r) => r.id === selectedId)
  // 지도에서 겹쳐 묶인 「N곳」 핀을 눌렀으면 그곳들만 보인다(#1174). 번호는 전체 결과의 번호 그대로다.
  const listed = results.map((r, i) => ({ r, n: i + 1 })).filter(({ r }) => !group || group.includes(r.id))

  function pinIt(r: SearchResultView) {
    const req = searchPinRequest(r.dto)
    if (!req) return
    create.mutate(
      req,
      {
        onSuccess: (pin) => {
          const name = pin.place_name ?? r.dto.place_name
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
    const { lat, lng } = r.dto
    // 지도 자리 메뉴에서 고른 곳은 친 검색어가 없어 가게 이름을 검색어로 쓴다 — 지도를 열 때 그 이름으로 위치를 다시 찾는다.
    // 체인점처럼 같은 이름이 많으면 다른 지점이 잡힐 수 있다(#1549 주의).
    const req = livePinRequest(r.dto, query ?? r.name, memo)
    if (!req) return
    create.mutate(
      req,
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

  if (search.isPending) return <CardSkeleton label="찾는 중…" />
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
        mood="sad"
        title="링크의 장소를 찾지 못했어요"
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
  if (source?.kind === 'tap' && results.length === 0 && nearby.length === 0) {
    // 지어내지 않는다(가드레일 2). 없으면 이름 검색으로 남기게 한다(api-spec GET /places/nearest).
    return (
      <EmptyState mood="sad" title="누른 곳 가까이에 찍을 수 있는 장소가 없어요" action={<SearchAgainButton onClose={close} label="검색으로 남기기" />}>
        지도에서 장소 바로 위를 다시 누르거나, 장소 이름으로 검색해 보세요.
      </EmptyState>
    )
  }
  if (results.length === 0 && nearby.length === 0) {
    // 흔한 말의 오타(「중곡집」)면 고친 말로 다시 찾게 한다. 아니면 검색어를 지우고 바로 다시 입력하게(#351).
    const fixed = query ? suggestQuery(query) : null
    return <NoResults query={query} fixed={fixed} onRetry={() => fixed && submit(fixed, near)} onClose={close} />
  }

  if (selected) {
    return (
      <div className="space-y-3">
        <PanelBackLink
          label={group ? `이 자리의 장소 ${listed.length}곳` : source?.kind === 'tap' ? '누른 곳 근처 장소' : `검색 결과 ${results.length}곳`}
          onBack={() => select(null)}
        />
        <div>
          <SheetTitle as="h3">{selected.name}</SheetTitle>
          <p className="text-body text-ink-600">{selected.meta}</p>
          {selected.far && <p className="text-body font-semibold text-warn-text">
            <Sentences text="현재 보고 있는 지도 중심에서 멀리 있는 장소예요. 다른 지역의 같은 이름 장소일 수 있어요" />
          </p>}
        </div>
        {/* 핀 상세와 같은 블로그 사진 줄(#1681). 자체 DB에 없는 장소는 사진을 찾을 주소가 없어 그리지 않는다. */}
        {!selected.unsupported && <ResultPhotos key={selected.id} placeId={selected.id} />}
        {(selected.address || selected.url || selected.naverUrl) && (
          <div className="space-y-2 rounded-xl bg-ink-50 p-3.5 text-body">
            {selected.address && <p className="text-ink-700">{selected.address}</p>}
            {/* 핀 상세와 같은 두 링크 — 찍기 전에도 네이버 지도로 볼 수 있다(#1554). */}
            <div className="flex flex-wrap gap-x-4">
              {selected.url && (
                <a href={selected.url} target="_blank" rel="noopener noreferrer" className="btn-link">
                  카카오맵에서 자세히 보기 <ExternalLink size={14} aria-hidden="true" />
                </a>
              )}
              {selected.naverUrl && (
                <a href={selected.naverUrl} target="_blank" rel="noopener noreferrer" className="btn-link">
                  네이버 지도에서 보기 <ExternalLink size={14} aria-hidden="true" />
                </a>
              )}
            </div>
          </div>
        )}
        {selected.canLeaveLive && !selected.alreadyPinned ? (
          <LiveLeaveForm category={selected.dto.category} pending={create.isPending} onSubmit={(input) => pinLive(selected, input)} />
        ) : (
          <PinItButton result={selected} filled pending={create.isPending} onPin={() => pinIt(selected)} />
        )}
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {group && <PanelBackLink label={`검색 결과 ${results.length}곳`} onBack={() => showGroup(null)} />}
      {/* 자체 DB 결과가 없고 카카오 근처 장소만 있으면(#1549) 빈 목록을 그리지 않는다. */}
      {listed.length > 0 && <ol className="space-y-2">
        {listed.map(({ r, n }) => (
          <li
            key={r.id}
            className={`flex items-center gap-3 rounded-xl border p-3 ${r.unsupported && !r.canLeaveLive ? 'border-ink-200 opacity-60' : 'border-ink-200'}`}
          >
            <span className="flex size-6 shrink-0 items-center justify-center rounded-full border-2 border-brand-600 text-xs font-bold text-link">
              {n}
            </span>
            <button type="button" onClick={() => select(r.id)} className="press -mx-1.5 min-w-0 flex-1 rounded-md px-1.5 text-left">
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
      </ol>}
      {nearby.length > 0 && !group && <NearbyList list={nearby} onSelect={select} />}
    </div>
  )
}

/**
 * 「카카오에서 찾은 근처 장소」(#1549). 자체 DB에 없는 가게라 장소 정보·AI 추천·동선에는 못 쓰고 핀으로만 남는다(#382).
 * 카카오 결과는 보이기만 하고 저장하지 않는다(#53). 지도에는 번호 핀을 그리지 않아 번호가 없다.
 */
function NearbyList({ list, onSelect }: { list: SearchResultView[]; onSelect: (id: string) => void }) {
  return (
    <section aria-labelledby="nearby-kakao" className="space-y-2 pt-2">
      <div>
        <h3 id="nearby-kakao" className="text-sm font-bold text-ink-900">
          카카오에서 찾은 근처 장소
        </h3>
        <p className="text-xs text-ink-500">장소 정보 없이 핀만 남아요</p>
      </div>
      <ul className="space-y-2">
        {list.map((r) => (
          <li key={r.id} className="flex items-center gap-3 rounded-xl border border-ink-200 p-3">
            <button type="button" onClick={() => onSelect(r.id)} className="press -mx-1.5 min-w-0 flex-1 rounded-md px-1.5 text-left">
              <p className="truncate font-bold text-ink-900">{r.name}</p>
              <p className="truncate text-xs text-ink-500">{r.meta}</p>
            </button>
            {r.alreadyPinned ? (
              <span className="shrink-0 text-xs text-ink-500">이미 지도에 있어요</span>
            ) : (
              <button type="button" onClick={() => onSelect(r.id)} className="btn-outline btn-sm shrink-0">
                핀 남기기
              </button>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}

/** 검색창을 비우고 다시 입력하게 한다(#351). */
/**
 * 이름 검색 0곳. 다음 행동은 검색어를 지우고 바로 다시 입력하기(#351)이고,
 * 그 아래 친 검색어 그대로 카카오맵에서 찾는 출구를 둔다(#905, 새 창). 링크를 못 받으면 출구만 숨긴다.
 */
function NoResults({ query, fixed, onRetry, onClose }: { query: string | null; fixed: string | null; onRetry: () => void; onClose: () => void }) {
  return (
    <EmptyState
      mood="sad"
      title="찾는 장소가 없어요"
      action={
        <div className="flex flex-col items-center gap-2">
          {fixed ? (
            <button type="button" onClick={onRetry} className="btn-primary btn-md">
              ‘{fixed}’ 찾아보기
            </button>
          ) : (
            <SearchAgainButton onClose={onClose} label="검색어 지우고 다시 찾기" />
          )}
          {query && <KakaoMapExit query={query} />}
        </div>
      }
    >
      {fixed ? `혹시 ‘${fixed}’${josa(fixed, '을', '를')} 찾으셨나요?` : '이름을 짧게 줄여 보거나, 다른 이름으로 찾아보세요'}
    </EmptyState>
  )
}

function KakaoMapExit({ query }: { query: string }) {
  const { data } = useExternalSearchQuery(query)
  return data ? <ExternalSearchLink search={data} className="btn-link text-sm" /> : null
}

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
 * 한마디 칸 예시는 분류를 따른다 — 검색 결과의 분류(`category`), 링크로 열었으면 고른 분류(#1461).
 */
function LiveLeaveForm({
  askName = false,
  category: known,
  pending,
  onSubmit,
}: {
  askName?: boolean
  category?: PinCategory | null
  pending: boolean
  onSubmit: (input: LiveInput) => void
}) {
  const [memo, setMemo] = useState('')
  const [name, setName] = useState('')
  const [category, setCategory] = useState<PinCategory | null>(null)
  const ready = !askName || (name.trim() !== '' && category !== null)
  return (
    <div className="space-y-2.5">
      <div className="rounded-xl bg-ink-50 p-3.5 text-body text-ink-700">
        <p className="font-semibold text-ink-900">장소 정보가 없는 곳이에요</p>
        <p className="mt-0.5"><Sentences text="상세 데이터가 없어 AI 추천과 동선에는 반영되지 않지만, 지도에 핀을 남겨 함께 이야기를 나눌 수 있어요." /></p>
      </div>
      {askName && (
        <>
          <label className="block space-y-1.5">
            <span className="block text-body font-bold text-ink-900">장소 이름</span>
            <TextField value={name} onChange={setName} maxLength={NAME_MAX} placeholder="카카오맵에 나온 이름 그대로" clearLabel="이름 지우기" />
          </label>
          <p className="text-xs text-ink-500"><Sentences text="지도를 열 때 이 이름으로 카카오맵에서 위치를 찾아요" /></p>
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
      <TextArea id="live-pin-memo" value={memo} onChange={setMemo} maxLength={MEMO_MAX} placeholder={inputExample(category ?? known, 'memo')} rows={2} clearLabel="한마디 지우기" />
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
    return <span className="shrink-0 text-xs text-ink-500">{result.dto.category ? '핀으로 찍을 수 없는 카테고리예요' : '카테고리를 알 수 없는 장소예요'}</span>
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

/** 검색 결과 상세의 블로그 사진 줄(#1681). 핀 상세의 `PinPhotos`와 같은 모양이다. */
function ResultPhotos({ placeId }: { placeId: string }) {
  const photos = usePlacePhotosQuery(placeId)
  return (
    <div className="py-1">
      <BlogPhotos photos={photos.data} loading={photos.isPending} failed={photos.isError} />
    </div>
  )
}
