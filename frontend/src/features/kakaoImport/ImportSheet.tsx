import { useId, useState } from 'react'

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
import { pinsCenter, useLinkImport } from './queries'

const OUTCOME: Record<NonNullable<ImportRow['outcome']>, { label: string; tag: string }> = {
  created: { label: '찍었어요', tag: 'tag-good' },
  duplicate: { label: '이미 있음', tag: 'tag-neutral' },
  rejected: { label: '못 찍었어요', tag: 'tag-warn' },
}

type Imp = ReturnType<typeof useLinkImport>
type Entry = { row: ImportRow; i: number }

/**
 * 카톡 대화에서 핀 가져오기(기획안 5-9, #578, #1046). 붙여넣은 대화에서 지도 링크(네이버·카카오·구글)와 공유 글의 상호명·주소만
 * 브라우저 안에서 읽고, 대화 원문은 서버로 보내지도 저장하지도 않는다(읽는 순간 입력칸을 비운다).
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
  const imp = useLinkImport(mapId)
  const near = pinsCenter(usePinsQuery(mapId).data)
  return (
    <ModalSheet label="카톡 대화에서 핀 가져오기" onClose={onClose}>
      <SheetTitle>카톡 대화에서 핀 가져오기</SheetTitle>
      {imp.phase === 'paste' ? (
        <PasteStep onStart={(text) => imp.start(text, near)} />
      ) : (
        <ReviewStep imp={imp} onClose={onClose} onOpenOne={onOpenOne} onSearchName={onSearchName} />
      )}
    </ModalSheet>
  )
}

function PasteStep({ onStart }: { onStart: (text: string) => boolean }) {
  const [text, setText] = useState('')
  const [none, setNone] = useState(false)
  const id = useId()
  return (
    <div className="mt-1 space-y-3">
      <p className="text-sm text-ink-500">
        대화를 복사하거나 「대화 내보내기」로 받은 글을 붙여넣어 주세요. 지도 링크와 공유한 가게 이름·주소만 읽고, 대화 내용은 보내지도 남기지도 않아요.
      </p>
      <label htmlFor={id} className="sr-only">
        카톡 대화
      </label>
      <textarea
        id={id}
        value={text}
        onChange={(e) => {
          setText(e.target.value)
          setNone(false)
        }}
        rows={6}
        placeholder="여기에 대화를 붙여넣기"
        className="field w-full resize-none py-3"
      />
      {none && <p className="text-sm text-warn-text">지도 링크를 찾지 못했어요. 링크가 포함된 대화 구간을 붙여넣어 주세요</p>}
      <button
        type="button"
        disabled={!text.trim()}
        onClick={() => {
          const ok = onStart(text)
          // 대화 원문은 읽자마자 버린다 — 링크가 없으면 고쳐 붙일 수 있게 남긴다.
          if (ok) setText('')
          else setNone(true)
        }}
        className="btn-primary btn-lg w-full"
      >
        지도 링크 찾기
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

function ReviewStep({ imp, onClose, onOpenOne, onSearchName }: { imp: Imp; onClose: () => void; onOpenOne: (url: string) => void; onSearchName: (name: string) => void }) {
  const entries = imp.rows.map((row, i) => ({ row, i, state: rowState(row) }))
  const of = (s: string) => entries.filter((e) => e.state === s)
  const found = of('found')
  const confirm = of('confirm')
  const search = of('search')
  const needsName = of('needsName')
  const already = of('already')
  const failed = of('failed')
  const checking = of('checking').length
  const busy = imp.phase !== 'review'
  const done = imp.phase === 'done'
  const count = (s: NonNullable<ImportRow['outcome']>) => {
    // 같은 장소로 묶인 줄은 한 곳으로 센다.
    const keys = new Set(entries.filter((e) => e.row.outcome === s).map((e) => placeKey(e.row) ?? `#${e.i}`))
    return keys.size
  }

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
        <p className="text-sm text-ink-500">
          지도 링크 {imp.rows.length}개를 찾았어요
          {checking > 0 && imp.phase === 'checking' && ` · 확인하는 중 ${imp.rows.length - checking}/${imp.rows.length}`}
        </p>
        {imp.found > imp.rows.length && <p className="text-xs text-warn-text">앞부분만 읽었어요. 뒤쪽 대화를 잘라 다시 넣어 주세요</p>}
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
          <p className="text-xs text-ink-500">공유한 곳과 주소가 같은 곳이에요. 이름이 달라서 직접 확인해 주세요</p>
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
          <p className="text-xs text-ink-500">우리 장소 데이터에서 바로 찾지 못했어요. 이름으로 찾은 곳에서 골라 주세요</p>
          {imp.searchPaused && (
            <div className="mt-2 flex items-center gap-2">
              <p className="text-xs text-warn-text">너무 빨리 찾고 있어요. 잠시 뒤 이어서 찾아 주세요</p>
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
          <p className="text-xs text-ink-500">링크에 장소 번호만 있어요. 같이 온 말을 보고 하나씩 찍어 주세요</p>
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
              읽지 못한 링크 {failed.length}개 · {[...new Set(failed.map(({ row }) => linkErrorMessage(row.item?.error_code)))].join(' · ')}
            </p>
          )}
        </section>
      )}

      {done ? (
        <div className="space-y-2">
          <p className="text-sm font-bold text-ink-900">
            찍었어요 {count('created')}곳 · 이미 있음 {count('duplicate')}곳 · 못 찍음 {count('rejected')}곳
          </p>
          <div className="grid grid-cols-2 gap-2">
            <button type="button" onClick={imp.reset} className="btn-neutral btn-md">
              다른 대화 붙여넣기
            </button>
            <button type="button" onClick={onClose} className="btn-primary btn-md">
              닫기
            </button>
          </div>
        </div>
      ) : (
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
                {pickable(p) ? [p.category, p.address].filter(Boolean).join(' · ') : '핀으로 남길 수 없는 분류예요'}
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

/**
 * 마킹 탭 제목 줄의 「카톡 대화에서 가져오기」. 시트가 떠 있는 동안 지도 버튼을 숨긴다(지도 정보 모달과 같은 규칙).
 * 「하나씩 찍기」는 시트를 닫고 그 링크를 검색 시트(#487)에, 「직접 찾기」는 그 이름을 검색 시트에 연다 — 진행은 남아 있어 다시 열면 이어진다.
 */
export function ImportButton({ mapId }: { mapId: string }) {
  const [open, setOpen] = useState(false)
  const setModalOpen = useSheetStore((s) => s.setModalOpen)
  const pins = usePinsQuery(mapId).data
  const toggle = (next: boolean) => {
    setOpen(next)
    setModalOpen(next)
  }
  const near: LatLng | null = pinsCenter(pins)
  return (
    <>
      <button type="button" onClick={() => toggle(true)} className="btn-link shrink-0 text-sm">
        카톡 대화에서 가져오기
      </button>
      {open && (
        <ImportSheet
          mapId={mapId}
          onClose={() => toggle(false)}
          onOpenOne={(url) => {
            toggle(false)
            useSearchStore.getState().openLink(url, null)
            useSheetStore.getState().setStage('map', 2)
          }}
          onSearchName={(name) => {
            toggle(false)
            useSearchStore.getState().submit(name.slice(0, 50), near)
            useSheetStore.getState().setStage('map', 2)
          }}
        />
      )}
    </>
  )
}
