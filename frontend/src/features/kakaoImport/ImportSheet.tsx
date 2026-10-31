import { useId, useState } from 'react'

import ErrorText from '@/ErrorText'
import { useSearchStore } from '@/features/search/searchStore'
import ModalSheet from '@/features/shell/ModalSheet'
import { useSheetStore } from '@/features/shell/sheetStore'
import { showToast } from '@/features/shell/toast'
import Checkbox from '@/ui/Checkbox'
import SheetTitle from '@/ui/SheetTitle'

import { linkErrorMessage, rowPlace, rowState, type ImportRow } from './model'
import { useLinkImport } from './queries'

const OUTCOME: Record<NonNullable<ImportRow['outcome']>, { label: string; tag: string }> = {
  created: { label: '찍었어요', tag: 'tag-good' },
  duplicate: { label: '이미 있음', tag: 'tag-neutral' },
  rejected: { label: '못 찍었어요', tag: 'tag-warn' },
}

/**
 * 카톡 대화에서 핀 가져오기(기획안 5-9, #578). 붙여넣은 대화에서 구글맵·카카오맵 링크만 브라우저 안에서 뽑고,
 * 대화 원문은 서버로 보내지도 저장하지도 않는다(뽑는 순간 입력칸을 비운다).
 * 짝이 있는 장소는 골라서 한꺼번에 찍고, 이름이 필요한 링크는 「하나씩 찍기」로 링크 하나 붙여넣기(#487) 화면에 넘긴다.
 */
export default function ImportSheet({ mapId, onClose, onOpenOne }: { mapId: string; onClose: () => void; onOpenOne: (url: string) => void }) {
  const imp = useLinkImport(mapId)
  return (
    <ModalSheet label="카톡 대화에서 핀 가져오기" onClose={onClose}>
      <SheetTitle>카톡 대화에서 핀 가져오기</SheetTitle>
      {imp.phase === 'paste' ? <PasteStep onStart={imp.start} /> : <ReviewStep imp={imp} onClose={onClose} onOpenOne={onOpenOne} />}
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
        대화를 복사하거나 「대화 내보내기」로 받은 글을 붙여넣어 주세요. 구글맵·카카오맵 링크만 골라내고, 대화 내용은 보내지도 남기지도 않아요.
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
          // 대화 원문은 링크를 뽑자마자 버린다 — 링크가 없으면 고쳐 붙일 수 있게 남긴다.
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

function ReviewStep({ imp, onClose, onOpenOne }: { imp: ReturnType<typeof useLinkImport>; onClose: () => void; onOpenOne: (url: string) => void }) {
  const rows = imp.rows.map((row, i) => ({ row, i, state: rowState(row) }))
  const of = (s: string) => rows.filter((r) => r.state === s)
  const found = of('found')
  const oneByOne = of('oneByOne')
  const already = of('already')
  const failed = of('failed')
  const checking = of('checking').length
  const picked = found.filter((r) => r.row.picked && !r.row.outcome).length
  const done = imp.phase === 'done'
  const count = (s: NonNullable<ImportRow['outcome']>) => rows.filter((r) => r.row.outcome === s).length

  return (
    <div className="mt-1 space-y-5">
      <p className="text-sm text-ink-500">
        {imp.found > imp.rows.length ? `지도 링크 ${imp.found}개 중 앞의 ${imp.rows.length}개를 확인해요` : `지도 링크 ${imp.rows.length}개를 찾았어요`}
        {checking > 0 && imp.phase === 'checking' && ` · 확인하는 중 ${imp.rows.length - checking}/${imp.rows.length}`}
      </p>

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
          <h3 className="text-sm font-bold text-ink-900">찍을 수 있는 곳 {found.length}</h3>
          <ul className="mt-1 divide-y divide-ink-100">
            {found.map(({ row, i }) => {
              const place = rowPlace(row)
              return (
                <li key={row.url} className="flex items-center gap-2">
                  <Checkbox checked={row.picked} onChange={() => imp.toggle(i)} disabled={Boolean(row.outcome) || imp.phase !== 'review'}>
                    <span className="block truncate font-bold text-ink-900">{place?.place_name}</span>
                    <span className="block truncate text-xs text-ink-500">{[place?.category, place?.address].filter(Boolean).join(' · ')}</span>
                  </Checkbox>
                  {row.outcome && <span className={`tag ${OUTCOME[row.outcome].tag}`}>{OUTCOME[row.outcome].label}</span>}
                </li>
              )
            })}
          </ul>
        </section>
      )}

      {oneByOne.length > 0 && (
        <section>
          <h3 className="text-sm font-bold text-ink-900">하나씩 찍을 곳 {oneByOne.length}</h3>
          <p className="text-xs text-ink-500">우리 장소 데이터에 짝이 없어요. 이름으로 찾거나 이름을 적어 남겨요</p>
          <ul className="mt-1 divide-y divide-ink-100">
            {oneByOne.map(({ row, i }) => (
              <li key={row.url} className={`flex min-h-11 items-center gap-2 py-1 ${row.opened ? 'opacity-60' : ''}`}>
                <span className="min-w-0 flex-1">
                  {/* 링크 속 이름은 사용자가 붙인 값이라 문장에 섞지 않는다(#717). 카카오 링크는 이름이 없어 링크를 보인다. */}
                  {row.item?.result?.name_hint ? (
                    <q className="block truncate font-bold text-ink-900">{row.item.result.name_hint}</q>
                  ) : (
                    <span className="block truncate text-xs text-ink-600">{row.url}</span>
                  )}
                </span>
                <button
                  type="button"
                  onClick={() => {
                    imp.markOpened(i)
                    onOpenOne(row.url)
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
          disabled={picked === 0 || imp.phase !== 'review'}
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

/**
 * 마킹 탭 제목 줄의 「카톡 대화에서 가져오기」. 시트가 떠 있는 동안 지도 버튼을 숨긴다(지도 정보 모달과 같은 규칙).
 * 「하나씩 찍기」는 시트를 닫고 그 링크를 검색 시트(#487)에 연다 — 진행은 남아 있어 다시 열면 이어진다.
 */
export function ImportButton({ mapId }: { mapId: string }) {
  const [open, setOpen] = useState(false)
  const setModalOpen = useSheetStore((s) => s.setModalOpen)
  const toggle = (next: boolean) => {
    setOpen(next)
    setModalOpen(next)
  }
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
        />
      )}
    </>
  )
}
