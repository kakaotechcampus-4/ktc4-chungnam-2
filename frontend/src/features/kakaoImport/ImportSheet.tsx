import { useEffect, useId, useRef, useState } from 'react'

import ErrorText from '@/ErrorText'
import { usePinsQuery } from '@/features/map/queries'
import type { LatLng } from '@/features/search/model'
import { useSearchStore } from '@/features/search/searchStore'
import ModalSheet from '@/features/shell/ModalSheet'
import { useSheetStore } from '@/features/shell/sheetStore'
import { showToast } from '@/features/shell/toast'
import Checkbox from '@/ui/Checkbox'
import Radio from '@/ui/Radio'
import SheetTitle from '@/ui/SheetTitle'

import { foundLabel, linkErrorMessage, placeKey, rowName, rowPlace, rowState, rowTitle, toPinRequest, type ImportRow, type PlaceSearchResultDto } from './model'
import { closeImport, openImport, pinsCenter, useImportOpen, useLinkImport, type AddResult } from './queries'
import type { DayRange } from './share'

const OUTCOME: Record<NonNullable<ImportRow['outcome']>, { label: string; tag: string }> = {
  created: { label: '찍었어요', tag: 'tag-good' },
  duplicate: { label: '이미 있어요', tag: 'tag-neutral' },
  rejected: { label: '못 찍었어요', tag: 'tag-warn' },
}

type Imp = ReturnType<typeof useLinkImport>
type Entry = { row: ImportRow; i: number }

/**
 * 카톡 대화에서 핀 가져오기(기획안 5-9, #578, #1046). 「대화 내보내기」 .txt 파일에서 고른 기간의 지도 링크(네이버·카카오·구글)와
 * 공유 글의 상호명·주소만 브라우저 안에서 읽고, 대화 원문은 서버로 보내지도 저장하지도 않는다(#1139 — 붙여넣기는 없앴다).
 * 링크마다 4단으로 푼다(#1046): 서버가 찾은 곳 → 같은 주소 후보 확인 → 이름으로 찾은 후보 → 직접 찾기·하나씩 찍기.
 */
export default function ImportSheet({
  mapId,
  onClose,
  onOpenOne,
  onSearchName,
}: {
  mapId: string
  onClose: () => void
  onOpenOne: (url: string) => void
  onSearchName: (name: string) => void
}) {
  const near = pinsCenter(usePinsQuery(mapId).data)
  const imp = useLinkImport(mapId, near)
  const hasRows = imp.rows.length > 0
  return (
    <ModalSheet label="카톡 대화에서 핀 가져오기" onClose={onClose}>
      <SheetTitle>카톡 대화에서 핀 가져오기</SheetTitle>
      {/* 파일 넣기는 늘 있다 — 다른 대화 파일을 넣으면 아래 목록에 새 링크만 더한다(#1045). */}
      <FileBox onAdd={imp.add} more={hasRows} />
      {hasRows && <ReviewStep imp={imp} onOpenOne={onOpenOne} onSearchName={onSearchName} />}
    </ModalSheet>
  )
}

const NOTICE: Record<Exclude<AddResult, 'added'>, string> = {
  noLinks: '이 기간에 지도 링크가 없어요. 기간을 넓혀 보세요',
  noDates: '날짜를 읽지 못했어요. 카톡에서 대화 내보내기로 받은 파일인지 확인해 주세요',
  full: '목록이 가득 차서 새 링크를 더하지 못했어요. 지금 목록을 찍고 완료된 것을 지운 뒤 다시 넣어 주세요',
}

/** .txt 만 받는다 — accept 는 고르는 창의 힌트일 뿐이라 이름·형식을 한 번 더 본다. */
const isTextFile = (file: File) => /\.txt$/i.test(file.name)

/**
 * 기간(여행 얘기를 한 날짜) 두 칸 + 대화 파일 넣기(#1139). 기간을 고르기 전에는 파일을 넣지 못한다.
 * 파일은 브라우저 안에서만 읽고 바로 버린다. 기간은 시트가 열려 있는 동안 남아서 다른 대화 파일을 같은 기간으로 더 넣을 수 있다.
 */
function FileBox({ onAdd, more }: { onAdd: (text: string, range: DayRange) => AddResult; more: boolean }) {
  const [range, setRange] = useState<DayRange>({ from: '', to: '' })
  const [notice, setNotice] = useState<string | null>(null)
  const [reading, setReading] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const errorId = useId()
  const wrongOrder = Boolean(range.from && range.to && range.from > range.to)
  const ready = Boolean(range.from && range.to) && !wrongOrder

  async function read(file: File) {
    setNotice(null)
    if (!isTextFile(file)) return setNotice('.txt 파일만 넣을 수 있어요')
    setReading(true)
    let text: string
    try {
      text = await file.text()
    } catch {
      setNotice('파일을 읽지 못했어요')
      return
    } finally {
      setReading(false)
    }
    const result = onAdd(text.replace(/^﻿/, ''), range)
    if (result !== 'added') setNotice(NOTICE[result])
  }

  const setDay = (patch: Partial<DayRange>) => {
    setRange((r) => ({ ...r, ...patch }))
    setNotice(null)
  }

  return (
    <div className="mt-1 space-y-3">
      {!more && <p className="text-sm text-ink-500">카톡에서 대화 내보내기로 받은 .txt 파일을 넣어 주세요. 대화 내용은 어디에도 보내거나 저장하지 않아요</p>}
      <fieldset>
        <legend className="mb-1.5 text-sm font-semibold text-ink-900">여행 얘기를 한 기간</legend>
        <div className="grid grid-cols-2 gap-2">
          <label className="block">
            <span className="mb-1 block text-xs text-ink-500">시작일</span>
            <input type="date" value={range.from} onChange={(e) => setDay({ from: e.target.value })} className="field w-full" />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-ink-500">종료일</span>
            <input
              type="date"
              value={range.to}
              min={range.from || undefined}
              onChange={(e) => setDay({ to: e.target.value })}
              aria-invalid={wrongOrder}
              aria-describedby={wrongOrder ? errorId : undefined}
              className="field w-full"
            />
          </label>
        </div>
        {wrongOrder && (
          <p id={errorId} className="mt-1.5 text-sm text-warn-text">
            종료일은 시작일과 같거나 뒤여야 해요
          </p>
        )}
      </fieldset>
      {/* 파일 고르는 창은 아래 버튼이 연다 — 숨긴 입력칸은 화면 읽기에서 빠지고 버튼 하나만 남는다. */}
      <input
        ref={input}
        type="file"
        accept=".txt,text/plain"
        aria-label="카톡 대화 파일"
        className="hidden"
        disabled={!ready || reading}
        onChange={(e) => {
          const file = e.target.files?.[0]
          // 같은 파일을 다른 기간으로 다시 넣을 수 있게 비운다.
          e.target.value = ''
          if (file) void read(file)
        }}
      />
      {notice && (
        <p role="alert" className="text-sm text-warn-text">
          {notice}
        </p>
      )}
      <button
        type="button"
        disabled={!ready || reading}
        onClick={() => input.current?.click()}
        className={more ? 'btn-outline btn-md w-full' : 'btn-primary btn-lg w-full'}
      >
        {reading ? '읽는 중…' : more ? '다른 대화 파일 더하기' : '대화 파일 넣기'}
      </button>
    </div>
  )
}

/** 링크는 제목이 아니라 보조로만 — 짧게 보여 주고 새 창으로 연다. */
function LinkRef({ url }: { url: string }) {
  const short = url.replace(/^https?:\/\/(www\.)?/, '').slice(0, 40)
  return (
    <a href={url} target="_blank" rel="noopener noreferrer" className="truncate text-xs text-ink-500 underline underline-offset-2">
      {short}
    </a>
  )
}

function ReviewStep({ imp, onOpenOne, onSearchName }: { imp: Imp; onOpenOne: (url: string) => void; onSearchName: (name: string) => void }) {
  const all = imp.rows.map((row, i) => ({ row, i, state: rowState(row) }))
  // 찍은 줄은 「찍음」으로 따로 접어 둔다 — 상태별 묶음에는 아직 찍지 않은 줄만.
  const doneRows = all.filter((e) => e.row.outcome)
  const entries = all.filter((e) => !e.row.outcome)
  const of = (s: string) => entries.filter((e) => e.state === s)
  const found = of('found')
  const confirm = of('confirm')
  const search = of('search')
  const needsName = of('needsName')
  const already = of('already')
  const failed = of('failed')
  const checking = of('checking').length
  const busy = imp.phase !== 'idle'

  // 다른 링크라도 같은 장소를 고르면 한 곳이다 — 처음 고른 줄만 세고, 뒤의 줄에는 「위와 같은 장소」를 단다.
  const firstOf = new Map<string, number>()
  for (const e of entries) {
    const key = e.row.picked ? placeKey(e.row) : undefined
    if (key && !firstOf.has(key)) firstOf.set(key, e.i)
  }
  const sameAsAbove = (e: Entry) => {
    const key = e.row.picked ? placeKey(e.row) : undefined
    return key !== undefined && firstOf.get(key) !== e.i
  }
  const picked = [...firstOf.values()].filter((i) => !imp.rows[i].outcome && toPinRequest(imp.rows[i])).length

  return (
    <div className="mt-1 space-y-5">
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <p className="min-w-0 flex-1 text-sm text-ink-500">
            {checking > 0 && imp.phase === 'checking'
              ? `지도 링크 ${imp.rows.length}개 중 ${imp.rows.length - checking}개 확인했어요`
              : `지도 링크 ${imp.rows.length}개`}
          </p>
          {(doneRows.length > 0 || already.length > 0) && (
            <button type="button" onClick={imp.clearDone} disabled={busy} className="btn-text text-sm">
              완료된 것 지우기
            </button>
          )}
          <button type="button" onClick={imp.clearAll} disabled={busy} className="btn-text text-sm">
            모두 비우기
          </button>
        </div>
        {imp.truncated && <p className="text-xs text-warn-text">목록이 가득 차서 일부 링크가 빠졌어요. 찍고 완료된 것을 지운 뒤 나머지 기간을 다시 넣어 주세요</p>}
      </div>

      {imp.error != null && (
        <div className="space-y-2">
          <ErrorText message={checking > 0 ? '링크를 다 확인하지 못했어요' : '핀을 찍지 못했어요'} error={imp.error} />
          {checking > 0 && (
            <button type="button" onClick={imp.retryCheck} className="btn-outline btn-sm">
              남은 링크 다시 확인
            </button>
          )}
        </div>
      )}

      {found.length > 0 && (
        <section>
          <h3 className="text-sm font-bold text-ink-900">찾은 곳 {found.length}</h3>
          <ul className="mt-1 divide-y divide-ink-100">
            {found.map((e) => {
              const place = rowPlace(e.row)
              const label = foundLabel(e.row)
              return (
                <li key={e.row.share.url} className="flex items-center gap-2">
                  <Checkbox checked={e.row.picked} onChange={() => imp.toggle(e.i)} disabled={Boolean(e.row.outcome) || busy}>
                    <span className="block truncate font-bold text-ink-900">{rowTitle(e.row)}</span>
                    <span className="block truncate text-xs text-ink-500">{[place?.category, place?.address].filter(Boolean).join(' · ')}</span>
                    {label && <span className="mt-0.5 block text-xs font-semibold text-[var(--good-text)]">{label}</span>}
                  </Checkbox>
                  <RowTags e={e} sameAsAbove={sameAsAbove(e)} />
                </li>
              )
            })}
          </ul>
        </section>
      )}

      {confirm.length > 0 && (
        <section>
          <h3 className="text-sm font-bold text-ink-900">이 장소가 맞나요? {confirm.length}</h3>
          <p className="text-xs text-ink-500">주소는 같은데 이름이 달라요. 같은 곳인지 확인해 주세요</p>
          <ul className="mt-1 divide-y divide-ink-100">
            {confirm.map((e) => {
              const candidate = e.row.item?.result?.address_candidates?.[0]
              if (!candidate) return null
              const on = e.row.picked && e.row.choice?.place_id === candidate.place_id
              return (
                <li key={e.row.share.url} className="flex items-center gap-2">
                  <Checkbox checked={on} onChange={() => imp.choose(e.i, on ? null : candidate)} disabled={Boolean(e.row.outcome) || busy}>
                    <span className="block truncate font-bold text-ink-900">{candidate.place_name}</span>
                    <span className="block truncate text-xs text-ink-500">{candidate.address}</span>
                    <span className="block truncate text-xs text-ink-500">
                      공유한 이름 <q>{rowName(e.row) ?? '모름'}</q>
                    </span>
                  </Checkbox>
                  <RowTags e={e} sameAsAbove={sameAsAbove(e)} />
                </li>
              )
            })}
          </ul>
        </section>
      )}

      {search.length > 0 && (
        <section>
          <h3 className="text-sm font-bold text-ink-900">이름으로 찾을 곳 {search.length}</h3>
          <p className="text-xs text-ink-500">이름으로 찾아봤어요. 맞는 곳을 골라 주세요</p>
          {imp.searchPaused && (
            <div className="mt-2 flex items-center gap-2">
              <p className="text-xs text-warn-text">찾을 곳이 많아 잠깐 멈췄어요. 조금 뒤에 이어서 찾아 주세요</p>
              <button type="button" onClick={imp.retrySearch} className="btn-outline btn-sm">
                이어서 찾기
              </button>
            </div>
          )}
          <ul className="mt-1 space-y-3">
            {search.map((e) => (
              <SearchRow key={e.row.share.url} e={e} imp={imp} busy={busy} sameAsAbove={sameAsAbove(e)} onSearchName={onSearchName} />
            ))}
          </ul>
        </section>
      )}

      {needsName.length > 0 && (
        <section>
          <h3 className="text-sm font-bold text-ink-900">이름 확인 필요 {needsName.length}</h3>
          <p className="text-xs text-ink-500">링크만으로는 어떤 곳인지 알 수 없어요. 같이 보낸 메시지를 보고 하나씩 찍어 주세요</p>
          <ul className="mt-1 divide-y divide-ink-100">
            {needsName.map(({ row, i }) => (
              <li key={row.share.url} className={`flex min-h-11 items-center gap-2 py-1.5 ${row.opened ? 'opacity-60' : ''}`}>
                <span className="min-w-0 flex-1 space-y-0.5">
                  {/* 같은 메시지의 말은 사람이 알아보는 데만 — 화면 메모리에만 있고 보내지 않는다(#1046). */}
                  {row.share.context?.map((line) => (
                    <span key={line} className="block truncate text-xs text-ink-600">
                      {line}
                    </span>
                  ))}
                  <LinkRef url={row.share.url} />
                </span>
                <button
                  type="button"
                  onClick={() => {
                    imp.markOpened(i)
                    onOpenOne(row.share.url)
                  }}
                  className="btn-outline btn-sm"
                >
                  하나씩 찍기
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {(already.length > 0 || failed.length > 0) && (
        <section className="space-y-1 text-xs text-ink-500">
          {already.length > 0 && <p>이미 지도에 있는 곳 {already.length}개는 뺐어요</p>}
          {failed.length > 0 && (
            <p>
              읽지 못한 링크가 {failed.length}개 있어요. {[...new Set(failed.map(({ row }) => linkErrorMessage(row.item?.error_code)))].join('. ')}
            </p>
          )}
        </section>
      )}

      {doneRows.length > 0 && (
        // 찍은 줄은 접어 둔다 — 새로고침하거나 대화를 더 넣어도 남아서, 무엇을 이미 찍었는지 볼 수 있다(#1045).
        <details className="rounded-xl bg-ink-50 px-3 py-2">
          <summary className="text-sm font-bold text-ink-900">찍은 곳 {new Set(doneRows.map((e) => placeKey(e.row) ?? e.row.share.url)).size}개</summary>
          <ul className="mt-1 divide-y divide-ink-100">
            {doneRows.map((e) => (
              <li key={e.row.share.url} className="flex min-h-11 items-center gap-2">
                <span className="min-w-0 flex-1 truncate text-body text-ink-700">{rowTitle(e.row)}</span>
                <RowTags e={e} sameAsAbove={false} />
              </li>
            ))}
          </ul>
        </details>
      )}

      {imp.lastSaved && (
        <p className="text-sm font-bold text-ink-900">
          {[
            imp.lastSaved.created > 0 && `${imp.lastSaved.created}곳을 찍었어요`,
            imp.lastSaved.duplicate > 0 && `${imp.lastSaved.duplicate}곳은 이미 있었어요`,
            imp.lastSaved.rejected > 0 && `${imp.lastSaved.rejected}곳은 못 찍었어요`,
          ]
            .filter(Boolean)
            .join('. ')}
        </p>
      )}

      {(picked > 0 || entries.length > 0) && (
        <button
          type="button"
          disabled={picked === 0 || busy}
          onClick={() =>
            void imp.save().then((created) => {
              if (created > 0) showToast(`${created}곳을 지도에 찍었어요`)
            })
          }
          className="btn-primary btn-lg w-full"
        >
          {imp.phase === 'saving' ? '찍는 중…' : imp.phase === 'checking' ? '링크 확인 중…' : `고른 ${picked}곳 지도에 찍기`}
        </button>
      )}
    </div>
  )
}

function RowTags({ e, sameAsAbove }: { e: Entry; sameAsAbove: boolean }) {
  if (e.row.outcome) return <span className={`tag ${OUTCOME[e.row.outcome].tag}`}>{OUTCOME[e.row.outcome].label}</span>
  if (sameAsAbove) return <span className="tag tag-neutral">위와 같은 곳</span>
  return null
}

/**
 * 이름은 아는데 짝이 없는 줄 — 이름으로 찾은 후보를 바로 아래에 보이고 하나 고른다(4단 해결의 3·4단계).
 * 공유 글 주소와 도로명주소가 같은 한 곳은 미리 골라 「주소가 같아요」를 단다. 그 밖에는 고르지 않은 채 둔다(자동 확정 금지).
 * 맞는 곳이 없으면 「직접 찾기」로 검색 화면을 그 이름으로 연다.
 */
function SearchRow({ e, imp, busy, sameAsAbove, onSearchName }: { e: Entry; imp: Imp; busy: boolean; sameAsAbove: boolean; onSearchName: (name: string) => void }) {
  const name = rowName(e.row) ?? ''
  const group = useId()
  const s = e.row.search
  const chosen = e.row.picked ? e.row.choice?.place_id : undefined
  const pickable = (p: PlaceSearchResultDto) => Boolean(toPinRequest({ ...e.row, choice: p }))
  return (
    <li className="space-y-1 rounded-xl border border-ink-200 p-3">
      <div className="flex items-start gap-2">
        <span className="min-w-0 flex-1">
          <span className="block truncate font-bold text-ink-900">{name}</span>
          {e.row.share.address ? <span className="block truncate text-xs text-ink-500">{e.row.share.address}</span> : <LinkRef url={e.row.share.url} />}
        </span>
        <RowTags e={e} sameAsAbove={sameAsAbove} />
      </div>
      {(!s || s.status === 'loading') && <p className="text-xs text-ink-500">이름으로 찾는 중…</p>}
      {s?.status === 'error' && <p className="text-xs text-warn-text">찾지 못했어요</p>}
      {s?.status === 'done' && s.results.length === 0 && <p className="text-xs text-ink-500">이 이름으로 찾은 곳이 없어요</p>}
      {s?.status === 'done' && s.results.length > 0 && (
        <div role="radiogroup" aria-label={`${name} 후보`}>
          {s.results.map((p) => (
            <Radio key={p.place_id} name={group} checked={chosen === p.place_id} onChange={() => imp.choose(e.i, p)} disabled={busy || Boolean(e.row.outcome) || !pickable(p)}>
              <span className="block truncate text-body font-semibold text-ink-900">
                {p.place_name}
                {e.row.auto && chosen === p.place_id && <span className="tag tag-good ml-1.5 align-middle">{foundLabel(e.row)}</span>}
              </span>
              <span className="block truncate text-xs text-ink-500">
                {pickable(p) ? [p.category, p.address].filter(Boolean).join(' · ') : '핀으로 찍을 수 없는 카테고리예요'}
              </span>
            </Radio>
          ))}
          <Radio name={group} checked={!chosen} onChange={() => imp.choose(e.i, null)} disabled={busy || Boolean(e.row.outcome)}>
            <span className="text-body text-ink-700">여기 없어요</span>
          </Radio>
        </div>
      )}
      {!e.row.outcome && (
        <button type="button" onClick={() => onSearchName(name)} className="btn-link text-sm">
          직접 찾기
        </button>
      )}
    </li>
  )
}

/** 마킹 탭 제목 줄의 「카톡 대화에서 가져오기」. 여는 일만 한다 — 시트는 `ImportSheetHost`가 화면 바뀜과 상관없이 한 자리에서 그린다(#1045). */
export function ImportButton({ mapId }: { mapId: string }) {
  return (
    <button type="button" onClick={() => openImport(mapId)} className="btn-link shrink-0 text-sm">
      카톡 대화에서 가져오기
    </button>
  )
}

/**
 * 가져오기 시트를 그리는 자리. 지도 화면(MapLayout)에 하나만 둔다 — 버튼이 있는 목록 머리는 검색·핀 상세·온보딩으로 바뀌면 통째로 빠지는데,
 * 시트를 그 안에서 그리면 열린 채 사라지면서 「모달 열림」(지도 버튼·핑고 조언·토스트를 숨김)이 꺼지지 않고 남았다(#1045).
 * 그래서 열림은 스토어에 두고, 모달 열림은 열려 있는 동안만 켠다 — 어떻게 닫히든(닫기·다른 지도·화면 나가기) cleanup 이 끈다.
 * 「하나씩 찍기」는 시트를 닫고 그 링크를, 「직접 찾기」는 그 이름을 검색 시트에 연다 — 목록은 남아 있어 다시 열면 이어진다.
 */
export function ImportSheetHost({ mapId }: { mapId: string }) {
  const open = useImportOpen(mapId)
  const setModalOpen = useSheetStore((s) => s.setModalOpen)
  const pins = usePinsQuery(mapId).data
  useEffect(() => {
    if (!open) return
    setModalOpen(true)
    return () => setModalOpen(false)
  }, [open, setModalOpen])
  // 다른 지도로 가거나 지도 화면을 떠나면 시트를 닫는다(목록은 지도별 저장소에 남는다).
  useEffect(() => () => closeImport(), [mapId])
  if (!open) return null
  const near: LatLng | null = pinsCenter(pins)
  return (
    <ImportSheet
      mapId={mapId}
      onClose={closeImport}
      onOpenOne={(url) => {
        closeImport()
        useSearchStore.getState().openLink(url, null)
        useSheetStore.getState().setStage('map', 2)
      }}
      onSearchName={(name) => {
        closeImport()
        useSearchStore.getState().submit(name.slice(0, 50), near)
        useSheetStore.getState().setStage('map', 2)
      }}
    />
  )
}
