import { useState } from 'react'

import { showToast } from '@/features/shell/toast'

import type { ExportFormat } from './model'
import { useShortlistExport } from './queries'

/**
 * 확정 리스트 내보내기(#484). 단톡방에 붙여 넣을 글자 복사와 파일 받기(메모장 txt, 엑셀 csv).
 * 순서·이름·분류·링크·메모는 서버가 정해 내려 준다 — 화면은 받은 내용을 그대로 옮긴다.
 */
export default function ShortlistExport({ mapId }: { mapId: string }) {
  const load = useShortlistExport(mapId)
  const [busy, setBusy] = useState(false)

  async function run(work: () => Promise<void>, failMessage: string) {
    setBusy(true)
    try {
      await work()
    } catch (err) {
      console.error('[shortlist] 내보내기 실패', err)
      showToast(failMessage)
    } finally {
      setBusy(false)
    }
  }

  const copy = () =>
    run(async () => {
      await copyText(load('txt').then((f) => f.blob.text()))
      showToast('확정 리스트를 복사했어요. 단톡방에 붙여 넣어 보세요')
    }, '확정 리스트를 복사하지 못했어요')

  const download = (format: ExportFormat) =>
    run(async () => {
      const file = await load(format)
      saveFile(file.blob, file.filename ?? `확정리스트.${format}`)
    }, '파일을 받지 못했어요')

  return (
    // 라벨은 한 줄, 버튼은 그 아래 줄에 — 라벨 옆에 붙이면 좁은 화면에서 셋째 버튼이 라벨 아래로 밀려 시작선이 어긋났다(#1511).
    <div className="mt-4 space-y-1 border-t border-ink-200 pt-3">
      <p className="text-xs font-bold text-ink-600">내보내기</p>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        <button type="button" disabled={busy} onClick={() => void copy()} className="btn-link text-sm">
          텍스트로 복사
        </button>
        <button type="button" disabled={busy} onClick={() => void download('txt')} className="btn-link text-sm">
          텍스트 파일(.txt)
        </button>
        <button type="button" disabled={busy} onClick={() => void download('csv')} className="btn-link text-sm">
          엑셀 파일(.csv)
        </button>
      </div>
    </div>
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
