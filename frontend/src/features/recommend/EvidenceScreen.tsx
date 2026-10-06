import { useState } from 'react'
import { Ban, ChevronLeft, X } from 'lucide-react'

import { ApiError } from '@/api'
import ErrorText from '@/ErrorText'
import { TAB_BAR_H } from '@/features/shell/layout'
import { showToast } from '@/features/shell/toast'
import Toaster from '@/features/shell/Toaster'

import { useAiStore } from './aiStore'
import { evidenceLabel, groupEvidence, type EvidenceLineDto, type RecommendRunDto, type RegionDto } from './model'
import { useConfirmRegionsMutation, useEvidenceQuery, useExecuteRunMutation, usePatchEvidenceMutation } from './queries'

/**
 * 근거 확인(Figma 6절, 최종기획안 5-5). 모델이 사유를 어떻게 읽었는지 보여 주고 사람이 고치게 한다.
 * - 꼭 지켜야 하는 조건: 구성원별 줄. 내 것만 × 로 뺀다(빼기 전에 한 번 묻는다 — 알레르기처럼 틀리면 안 되는 조건일 수 있다)
 * - 가능하면 맞춰주세요: 해시태그로 합친다. 내 몫이 든 태그에만 ×
 * - 지금까지 나온 의견에서: 원문 인용
 * 제약을 AI가 임의로 완화하지 않는다(가드레일 4) — 빼는 건 언제나 사람이다.
 */
export default function EvidenceScreen({ mapId, run }: { mapId: string; run: RecommendRunDto }) {
  const evidence = useEvidenceQuery(run.id)
  const patch = usePatchEvidenceMutation(run.id)
  const confirm = useConfirmRegionsMutation(run.id)
  const execute = useExecuteRunMutation(mapId)
  const setRun = useAiStore((s) => s.setRun)
  const [askRemove, setAskRemove] = useState<EvidenceLineDto | null>(null)
  const [conflict, setConflict] = useState<RegionDto[] | null>(null)
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState('')
  const groups = groupEvidence(evidence.data ?? [])
  const busy = confirm.isPending

  function toggle(line: EvidenceLineDto, active: boolean) {
    patch.mutate(
      { toggle: [{ id: line.id, is_active: active }] },
      {
        onSuccess: () =>
          !active &&
          showToast(`‘${evidenceLabel(line)}’을(를) 뺐어요`, { label: '되돌리기', onClick: () => toggle(line, true) }),
        onError: () => showToast('조건을 바꾸지 못했어요'),
      },
    )
  }

  function start(acceptUnion: boolean) {
    confirm.mutate(acceptUnion, {
      onSuccess: () => {
        setConflict(null)
        execute.mutate(run)
      },
      onError: (err) => {
        // 사람이 쓴 반경 사유끼리 안 겹친다 — 사람에게 묻는다(5-6-1). 다른 실패는 그대로 보여 준다.
        if (err instanceof ApiError && err.code === 'REGION_CONFLICT') {
          setConflict((err.detail?.regions as RegionDto[] | undefined) ?? [])
        }
      },
    })
  }

  return (
    <div className="fixed inset-x-0 top-0 z-30 flex flex-col bg-white" style={{ bottom: TAB_BAR_H }}>
      <header className="flex items-center gap-2 border-b border-ink-100 px-4 py-3">
        <button type="button" aria-label="추천 그만두기" onClick={() => setRun(mapId, undefined)} className="text-ink-900">
          <ChevronLeft size={22} />
        </button>
        <h1 className="text-lg font-bold text-ink-900">{run.category} 추천받기</h1>
      </header>

      <div className="flex-1 space-y-5 overflow-y-auto px-4 py-4">
        <div className="rounded-2xl border border-brand-300 bg-[var(--pingo-bg)] p-4">
          <p className="flex items-center gap-1.5 text-sm font-bold text-[var(--pingo-text)]">
            <span className="rounded bg-brand-600 px-1.5 text-[0.6875rem] text-white">AI</span> AI가 정리한 조건
          </p>
          <p className="mt-1 font-bold text-ink-900">이 조건으로 추천해도 될까요?</p>
          <p className="mt-1 text-xs text-ink-500">지금까지 남긴 의견을 이렇게 정리했어요.</p>
        </div>

        {evidence.isPending && <p className="text-sm text-ink-500">조건을 정리하는 중…</p>}
        {evidence.error && <ErrorText message="조건을 불러오지 못했어요" error={evidence.error} />}

        {groups.required.length > 0 && (
          <section className="space-y-2">
            <h2 className="text-sm font-bold text-ink-900">꼭 지켜야 하는 조건</h2>
            {groups.required.map((line) => (
              <div key={line.id} className="flex items-center gap-3 rounded-xl border border-ink-200 p-3">
                <Ban size={16} className="shrink-0 text-[var(--bad-line)]" aria-hidden="true" />
                <div className="min-w-0 flex-1">
                  <p className="text-[0.6875rem] text-ink-500">{line.author_display_name} · 반대 조건</p>
                  <p className="font-bold text-ink-900">{evidenceLabel(line)}</p>
                </div>
                {line.permissions.can_disable && (
                  <button type="button" aria-label={`${evidenceLabel(line)} 빼기`} onClick={() => setAskRemove(line)} className="text-ink-400">
                    <X size={18} />
                  </button>
                )}
              </div>
            ))}
          </section>
        )}

        {groups.preferred.length > 0 && (
          <section className="space-y-2">
            <h2 className="text-sm font-bold text-ink-900">가능하면 맞춰주세요</h2>
            <div className="flex flex-wrap gap-2">
              {/* 같은 태그는 하나로 합친다. 내 몫이 하나라도 있으면 × 를 붙인다. */}
              {mergeTags(groups.preferred).map(({ tag, mine }) => (
                <span key={tag} className="flex items-center gap-1 rounded-full border border-brand-300 bg-brand-50 px-3 py-1 text-sm font-semibold text-brand-700">
                  #{tag}
                  {mine && (
                    <button type="button" aria-label={`#${tag} 빼기`} onClick={() => toggle(mine, false)}>
                      <X size={14} />
                    </button>
                  )}
                </span>
              ))}
            </div>
          </section>
        )}

        {groups.reference.length > 0 && (
          <section className="space-y-2">
            <h2 className="text-sm font-bold text-ink-900">지금까지 나온 의견에서</h2>
            {groups.reference.map((line) => (
              <blockquote key={line.id} className="rounded-xl bg-ink-50 p-3 text-sm text-ink-700">
                <p className="text-[0.6875rem] text-ink-500">{line.author_display_name}</p>“{line.text}”
              </blockquote>
            ))}
          </section>
        )}

        {adding ? (
          <form
            onSubmit={(e) => {
              e.preventDefault()
              const text = draft.trim()
              if (!text) return
              patch.mutate({ add: [{ text }] }, {
                  onSuccess: () => {
                    setDraft('')
                    setAdding(false)
                  },
                  onError: () => showToast('조건을 더하지 못했어요'),
                })
            }}
            className="flex gap-2"
          >
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              maxLength={140}
              autoFocus
              aria-label="조건 더하기"
              placeholder="예: 비 오면 실내로 가고 싶어요"
              className="min-w-0 flex-1 rounded-xl border border-ink-300 px-3 py-2 text-sm"
            />
            <button type="submit" disabled={patch.isPending} className="rounded-xl border border-brand-600 px-3 text-sm font-semibold text-brand-600">
              더하기
            </button>
          </form>
        ) : (
          <button type="button" onClick={() => setAdding(true)} className="mx-auto block text-sm text-brand-600">
            조건 수정
          </button>
        )}

        {confirm.error && !(confirm.error instanceof ApiError && confirm.error.code === 'REGION_CONFLICT') && (
          <ErrorText message="지역을 확인하지 못했어요" error={confirm.error} />
        )}
      </div>

      {/* 이 화면은 시트가 없어서 토스트를 아래 버튼 줄 위에 띄운다. */}
      <div className="relative grid grid-cols-2 gap-2 border-t border-ink-100 p-4">
        <Toaster controlsVisible={false} />
        <button type="button" onClick={() => setRun(mapId, undefined)} className="rounded-xl border border-ink-300 py-3 font-semibold text-ink-900">
          취소
        </button>
        <button type="button" disabled={busy || evidence.isPending} onClick={() => start(false)} className="rounded-xl bg-brand-600 py-3 font-bold text-white disabled:opacity-50">
          {busy ? '찾기 시작하는 중…' : '네, 추천해주세요'}
        </button>
      </div>

      {askRemove && (
        <Confirm
          title="꼭 지켜야 하는 조건을 뺄까요?"
          body={`‘${evidenceLabel(askRemove)}’을(를) 빼면 이번 추천에서 이 조건으로 거르지 않아요. 알레르기처럼 한 번 틀리면 안 되는 조건이라면 그대로 두세요.`}
          note="내가 쓴 조건만 뺄 수 있어요. 다른 구성원의 조건은 그대로 남아요."
          cancel="그대로 두기"
          ok="빼기"
          danger
          onCancel={() => setAskRemove(null)}
          onOk={() => {
            toggle(askRemove, false)
            setAskRemove(null)
          }}
        />
      )}
      {conflict && (
        <Confirm
          title="두 조건을 동시에 만족하는 곳이 없어요"
          body="두 곳이 멀어서 한 번에 찾을 수 없어요. 각 지역에서 따로 찾아 결과를 나눠 보여 드릴 수 있어요."
          list={conflict.map((r) => r.label)}
          note="같은 사유가 남아 있는 동안에는 다시 묻지 않아요."
          cancel="근거를 다시 볼게요"
          ok="두 지역 각각 찾기"
          onCancel={() => setConflict(null)}
          onOk={() => start(true)}
        />
      )}
    </div>
  )
}

function mergeTags(lines: EvidenceLineDto[]) {
  const tags = new Map<string, EvidenceLineDto | null>()
  for (const line of lines) {
    const tag = evidenceLabel(line)
    const mine = line.permissions.can_disable ? line : null
    tags.set(tag, tags.get(tag) ?? mine)
  }
  return [...tags].map(([tag, mine]) => ({ tag, mine }))
}

/** 확인 창(Figma 근거 확인 계열). 빨강은 파괴적 동작(빼기)에만 쓴다. */
function Confirm({
  title,
  body,
  list,
  note,
  cancel,
  ok,
  danger = false,
  onCancel,
  onOk,
}: {
  title: string
  body: string
  list?: string[]
  note?: string
  cancel: string
  ok: string
  danger?: boolean
  onCancel: () => void
  onOk: () => void
}) {
  return (
    <div role="alertdialog" aria-modal="true" aria-label={title} className="fixed inset-0 z-50 flex items-center justify-center bg-scrim p-6">
      <div className="w-full max-w-sm space-y-2 rounded-2xl bg-white p-5">
        <p className="text-lg font-bold text-ink-900">{title}</p>
        {list && list.length > 0 && (
          <ul className="space-y-1 rounded-lg bg-ink-50 p-3 text-sm font-semibold text-ink-900">
            {list.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        )}
        <p className="text-sm text-ink-600">{body}</p>
        {note && <p className="text-xs text-ink-500">{note}</p>}
        <div className="grid grid-cols-2 gap-2 pt-2">
          <button type="button" onClick={onCancel} className="rounded-lg border border-ink-300 py-2.5 text-sm font-semibold">
            {cancel}
          </button>
          <button
            type="button"
            onClick={onOk}
            className={`rounded-lg py-2.5 text-sm font-bold text-white ${danger ? 'bg-[var(--action-danger)]' : 'bg-brand-600'}`}
          >
            {ok}
          </button>
        </div>
      </div>
    </div>
  )
}
