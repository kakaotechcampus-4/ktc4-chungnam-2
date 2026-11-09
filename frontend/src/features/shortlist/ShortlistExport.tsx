import { useEffect, useRef, useState } from 'react'
import { Check, Copy, FileSpreadsheet, FileText, Loader2, type LucideIcon } from 'lucide-react'

import { showToast } from '@/features/shell/toast'

import type { ExportFormat } from './model'
import { useShortlistExport } from './queries'

type Kind = 'copy' | ExportFormat

/** 타일 셋 — 무엇을 받는지 그림으로 먼저 알아보게 한다. 엑셀은 초록 표, 글자 파일은 회색 문서, 복사는 파랑. */
const TILES: { kind: Kind; title: string; sub: string; Icon: LucideIcon; tone: string }[] = [
  { kind: 'copy', title: '텍스트 복사', sub: '단톡방에 붙여 넣기', Icon: Copy, tone: 'bg-brand-50 text-link' },
  { kind: 'txt', title: '메모장 파일', sub: '.txt', Icon: FileText, tone: 'bg-ink-100 text-ink-700' },
  // 엑셀 표의 초록 — 좋음 토큰을 빌려 다크 모드도 따라간다.
  { kind: 'csv', title: '엑셀 파일', sub: '.csv', Icon: FileSpreadsheet, tone: 'bg-[var(--good-bg)] text-[var(--good-line)]' },
]

/** 끝났다는 표시(체크 + 「복사했어요」)를 타일에 남기는 시간. */
const DONE_MS = 2000

/**
 * 확정 리스트 내보내기(#484). 단톡방에 붙여 넣을 글자 복사와 파일 받기(메모장 txt, 엑셀 csv).
 * 순서·이름·분류·링크·메모는 서버가 정해 내려 준다 — 화면은 받은 내용을 그대로 옮긴다.
 * 글자 링크 셋이 눈에 띄지 않아서 그림 타일 셋으로 바꿨다. 누른 타일은 기다리는 동안 「받는 중…」, 끝나면 2초 동안 체크로 바뀐다.
 */
export default function ShortlistExport({ mapId }: { mapId: string }) {
  const load = useShortlistExport(mapId)
  const [busy, setBusy] = useState<Kind | null>(null)
  const [done, setDone] = useState<Kind | null>(null)
  const doneTimer = useRef<ReturnType<typeof setTimeout>>(undefined)
  useEffect(() => () => clearTimeout(doneTimer.current), [])

  async function run(kind: Kind, work: () => Promise<void>, failMessage: string) {
    setBusy(kind)
    try {
      await work()
      setDone(kind)
      clearTimeout(doneTimer.current)
      doneTimer.current = setTimeout(() => setDone(null), DONE_MS)
    } catch (err) {
      console.error('[shortlist] 내보내기 실패', err)
      showToast(failMessage)
    } finally {
      setBusy(null)
    }
  }

  const start = (kind: Kind) =>
    kind === 'copy'
      ? run(
          kind,
          async () => {
            await copyText(load('txt').then((f) => f.blob.text()))
            showToast('확정 리스트를 복사했어요. 단톡방에 붙여 넣어 보세요')
          },
          '확정 리스트를 복사하지 못했어요',
        )
      : run(
          kind,
          async () => {
            const file = await load(kind)
            saveFile(file.blob, file.filename ?? `확정리스트.${kind}`)
          },
          '파일을 받지 못했어요',
        )

  return (
    <section aria-labelledby="shortlist-export" className="mt-4 space-y-2 border-t border-ink-200 pt-3">
      <h3 id="shortlist-export" className="text-sm font-bold text-ink-900">
        내보내기
      </h3>
      <ul className="grid grid-cols-3 gap-2">
        {TILES.map(({ kind, title, sub, Icon, tone }) => (
          <li key={kind}>
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => void start(kind)}
              className="press flex h-full w-full flex-col items-center gap-1.5 rounded-xl bg-surface px-1 py-3 text-center ring-1 ring-ink-200 disabled:opacity-60"
            >
              <span aria-hidden="true" className={`flex size-10 items-center justify-center rounded-xl ${done === kind ? 'bg-[var(--good-bg)] text-[var(--good-line)]' : tone}`}>
                {busy === kind ? <Loader2 size={20} className="animate-spin motion-reduce:animate-none" /> : done === kind ? <Check size={20} strokeWidth={3} className="done-check" /> : <Icon size={20} />}
              </span>
              <span className="text-body font-bold text-ink-900">{busy === kind ? '받는 중…' : done === kind ? (kind === 'copy' ? '복사했어요' : '받았어요') : title}</span>
              <span className="text-xs text-ink-500">{sub}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

/**
 * Safari 는 누른 뒤 응답을 기다리고 나서 클립보드에 쓰면 막는다. 내용이 아직 오는 중이어도
 * 누른 순간 ClipboardItem 에 Promise 로 넘겨 쓰기를 시작한다. 없는 브라우저는 다 받은 뒤 쓴다.
 */
async function copyText(text: Promise<string>) {
  if (typeof ClipboardItem !== 'undefined' && navigator.clipboard.write) {
    const blob = text.then((t) => new Blob([t], { type: 'text/plain' }))
    return navigator.clipboard.write([new ClipboardItem({ 'text/plain': blob })])
  }
  return navigator.clipboard.writeText(await text)
}

function saveFile(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  // Safari·iOS는 받기를 늦게 시작한다 — 바로 지우면 받기가 말없이 실패한다(FileSaver.js 와 같은 40초).
  setTimeout(() => URL.revokeObjectURL(url), 40_000)
}
