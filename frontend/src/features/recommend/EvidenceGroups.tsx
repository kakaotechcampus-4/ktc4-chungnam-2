import { useState, type ReactNode } from 'react'
import { Ban, Check, Clock, Plus, Undo2, X } from 'lucide-react'

import { ApiError } from '@/api'
import { showToast } from '@/features/shell/toast'
import ConfirmDialog from '@/ui/ConfirmDialog'
import Notice from '@/ui/Notice'
import TextField from '@/ui/TextField'

import { evidenceLabel, evidenceLimitMessage, groupEvidence, notEnforcedNote, type EvidenceLineDto } from './model'
import { usePatchEvidenceMutation } from './queries'

/** 「+」 글 한 줄 길이(docs/api-spec.yaml EvidencePatchRequest.add[].text, 앞뒤 공백을 뗀 뒤 1~140자). */
const ADD_TEXT_MAX = 140

/** 상한(10회)을 다 쓰면 ×·＋도 서버가 막는다(429 RETRY_LIMIT, #845) — 결과 화면의 조건 카드가 읽기 전용이 된다. */
export const EVIDENCE_LOCKED = '추천을 다 받아서 조건을 더 고칠 수 없어요'

/**
 * 모델이 사유를 어떻게 읽었는지 묶어 보여 주고 사람이 고치게 한다(최종기획안 5-5). 결과 화면의 조건 카드와 지역 확인 화면이 같이 쓴다.
 * - 꼭 지킬 조건: 줄마다 칩(누가 썼는지는 칩 title). 내 것만 × 로 뺀다(빼기 전에 한 번 묻는다)
 * - 있으면 좋은 조건: 해시태그로 합친다. 내 몫이 든 태그에만 ×
 * - 적용 안 된 조건: 추천이 거르거나 점수에 쓰지 않는 줄(#742). 이유는 묶음 아래 한 줄. 알러지처럼 키가 없는 줄이 여기 온다
 * - 지금까지 나온 의견에서: 원문 인용
 * 글을 줄이려고 줄마다 카드 대신 칩을 쓴다(2026-10-31).
 * 제약을 AI가 임의로 완화하지 않는다(가드레일 4) — 빼는 건 언제나 사람이다. × 는 모델을 부르지 않고, ＋ 는 그 글만 모델이 정리한다.
 * `pending` 이 참인 줄은 「아직 적용 전」이다(고쳤지만 지금 결과에는 안 쓰인 줄). `removed` 는 지금 결과에 쓰였지만 뺀 줄이다.
 */
export default function EvidenceGroups({
  runId,
  lines,
  readOnly = false,
  pending = () => false,
  removed = [],
  onLocked,
}: {
  runId: string
  lines: EvidenceLineDto[]
  readOnly?: boolean
  pending?: (line: EvidenceLineDto) => boolean
  removed?: EvidenceLineDto[]
  onLocked?: () => void
}) {
  const patch = usePatchEvidenceMutation(runId)
  const [askRemove, setAskRemove] = useState<EvidenceLineDto | null>(null)
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState('')
  const [addLimit, setAddLimit] = useState<string | null>(null)
  const groups = groupEvidence(lines)
  const editable = (line: EvidenceLineDto) => !readOnly && line.permissions.can_disable

  /** 상한을 다 쓴 뒤 보낸 편집이면 읽기 전용으로 바꾸고 알린다. 아니면 false. */
  function locked(err: unknown) {
    if (!(err instanceof ApiError) || err.code !== 'RETRY_LIMIT') return false
    onLocked?.()
    showToast(EVIDENCE_LOCKED)
    return true
  }

  // 한 사유가 조건마다 줄로 나뉘어(#421) 같은 태그에 내 줄이 여럿일 수 있다 — 한 번에 같이 끄고 켠다.
  function toggle(target: EvidenceLineDto[], active: boolean) {
    patch.mutate(
      { toggle: target.map((l) => ({ id: l.id, is_active: active })) },
      {
        onSuccess: () =>
          !active &&
          showToast(`‘${evidenceLabel(target[0])}’을(를) 뺐어요`, { label: '되돌리기', onClick: () => toggle(target, true) }),
        onError: (err) => locked(err) || showToast('조건을 바꾸지 못했어요'),
      },
    )
  }

  // 조건은 칩 한 줄씩. 지금 결과에 안 쓰인 칩(고친 것)은 점선 + 시계 아이콘으로 표시한다 — 색만으로 뜻을 전하지 않는다.
  const chip = (line: EvidenceLineDto, icon: ReactNode, onRemove?: () => void) => (
    <li
      key={line.id}
      title={line.author_display_name ? `${line.author_display_name}의 조건` : undefined}
      className={`flex items-center gap-1 rounded-full border bg-white py-1 pl-2.5 pr-1 text-body font-semibold text-ink-900 ${
        pending(line) ? 'border-dashed border-[var(--warn-line)]' : 'border-ink-200'
      }`}
    >
      {icon}
      {evidenceLabel(line)}
      {pending(line) && <Clock size={12} className="text-[var(--warn-text)]" aria-label="아직 적용 전" />}
      {onRemove ? (
        <button type="button" aria-label={`${evidenceLabel(line)} 빼기`} onClick={onRemove} className="hit-44 text-ink-500">
          <X size={14} />
        </button>
      ) : (
        <span className="w-1.5" />
      )}
    </li>
  )
  const group = (title: string, children: ReactNode, note?: string) => (
    <section className="space-y-1.5">
      <h3 className="text-label text-ink-500">{title}</h3>
      <ul className="flex flex-wrap gap-1.5">{children}</ul>
      {note && <p className="text-xs text-ink-500">{note}</p>}
    </section>
  )
  // 쓰이지 않는 줄의 이유는 칩마다 적지 않고 묶음 아래 한 번만(이유가 같으면 한 줄).
  const unusedNotes = [...new Set(groups.unused.map(notEnforcedNote))].join(' · ')

  return (
    <div className="space-y-4">
      {groups.required.length > 0 &&
        group(
          '꼭 지킬 조건',
          groups.required.map((line) =>
            chip(
              line,
              // 묶음은 badge로 정한다 — 🚫에서 나왔다고 반대 조건인 게 아니고, ♥ 쪽 "꼭 ○○여야 해"도 여기 온다(#231·#427).
              line.wants === true ? (
                <Check size={12} className="shrink-0 text-[var(--good-line)]" aria-hidden="true" />
              ) : (
                <Ban size={12} className="shrink-0 text-[var(--bad-line)]" aria-hidden="true" />
              ),
              editable(line) ? () => setAskRemove(line) : undefined,
            ),
          ),
        )}

      {groups.preferred.length > 0 &&
        group(
          '있으면 좋은 조건',
          // 같은 태그는 하나로 합친다. 내 몫이 하나라도 있으면 × 를 붙인다.
          mergeTags(groups.preferred).map(({ tag, all, mine }) =>
            chip(
              { ...all[0], fact_label: null, text: `#${tag}` },
              null,
              !readOnly && mine.length > 0 ? () => toggle(mine, false) : undefined,
            ),
          ),
        )}

      {groups.unused.length > 0 &&
        group(
          '적용 안 된 조건',
          // 거르지 않는 줄이라 빼기 전에 묻지 않는다 — 되돌리기 토스트만.
          groups.unused.map((line) => chip(line, null, editable(line) ? () => toggle([line], false) : undefined)),
          unusedNotes,
        )}

      {removed.length > 0 &&
        group(
          '뺀 조건 · 다시 추천 때 반영',
          removed.map((line) => (
            <li key={line.id} className="flex items-center gap-1 rounded-full border border-dashed border-ink-300 py-1 pl-2.5 pr-1 text-body text-ink-500">
              <span className="line-through">{evidenceLabel(line)}</span>
              {editable(line) && (
                <button type="button" aria-label={`${evidenceLabel(line)} 다시 넣기`} onClick={() => toggle([line], true)} className="hit-44 text-brand-600">
                  <Undo2 size={14} />
                </button>
              )}
            </li>
          )),
        )}

      {groups.reference.length > 0 && (
        <section className="space-y-1.5">
          <h3 className="text-label text-ink-500">지금까지 나온 의견에서</h3>
          {groups.reference.map((line) => (
            <blockquote key={line.id} className="rounded-xl bg-ink-50 p-3 text-sm text-ink-700">
              <p className="text-label text-ink-500">{line.author_display_name}</p>“{line.text}”
            </blockquote>
          ))}
        </section>
      )}

      {readOnly ? null : addLimit ? (
        <Notice>{addLimit}</Notice>
      ) : adding ? (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            const text = draft.trim()
            if (!text) return
            patch.mutate(
              { add: [{ text }] },
              {
                onSuccess: () => {
                  setDraft('')
                  setAdding(false)
                },
                onError: (err) => {
                  if (locked(err)) return
                  // 상한(409 EVIDENCE_LIMIT)이면 입력을 닫고 이유를 남긴다. 숫자는 응답 detail.limit 에서(#720).
                  const limit = evidenceLimitMessage(err)
                  if (!limit) return showToast('조건을 더하지 못했어요')
                  setAddLimit(limit)
                  setAdding(false)
                },
              },
            )
          }}
          className="flex items-center gap-2"
        >
          <div className="min-w-0 flex-1">
            <TextField
              value={draft}
              onChange={setDraft}
              maxLength={ADD_TEXT_MAX}
              autoFocus
              label="조건 더하기"
              clearLabel="조건 지우기"
              placeholder="예: 비 오면 실내로 가고 싶어요"
            />
          </div>
          <button type="submit" disabled={patch.isPending || !draft.trim()} className="btn-link shrink-0 text-sm">
            {patch.isPending ? '정리하는 중…' : '더하기'}
          </button>
        </form>
      ) : (
        <button type="button" onClick={() => setAdding(true)} className="btn-link flex items-center gap-0.5 text-sm">
          <Plus size={14} aria-hidden="true" /> 조건 더하기
        </button>
      )}

      {askRemove && (
        <ConfirmDialog
          title="꼭 지켜야 하는 조건을 뺄까요?"
          body={`‘${evidenceLabel(askRemove)}’을(를) 빼면 다음 추천부터 이 조건으로 거르지 않아요.`}
          note="내가 쓴 조건만 뺄 수 있어요. 다른 구성원의 조건은 그대로 남아요."
          cancel="그대로 두기"
          ok="빼기"
          danger
          onCancel={() => setAskRemove(null)}
          onOk={() => {
            toggle([askRemove], false)
            setAskRemove(null)
          }}
        />
      )}
    </div>
  )
}

/** 같은 태그는 하나로 합친다. all = 그 태그의 줄 전부, mine = 그중 내 줄(뺄 수 있는 줄). */
function mergeTags(lines: EvidenceLineDto[]) {
  const tags = new Map<string, { all: EvidenceLineDto[]; mine: EvidenceLineDto[] }>()
  for (const line of lines) {
    const tag = evidenceLabel(line)
    const entry = tags.get(tag) ?? { all: [], mine: [] }
    entry.all.push(line)
    if (line.permissions.can_disable) entry.mine.push(line)
    tags.set(tag, entry)
  }
  return [...tags].map(([tag, v]) => ({ tag, ...v }))
}
