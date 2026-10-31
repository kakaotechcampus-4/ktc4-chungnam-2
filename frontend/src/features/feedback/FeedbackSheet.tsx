import { useState } from 'react'

import ErrorText from '@/ErrorText'
import ModalSheet from '@/features/shell/ModalSheet'
import { showToast } from '@/features/shell/toast'
import SheetTitle from '@/ui/SheetTitle'

import { FEEDBACK_CATEGORIES, feedbackErrorMessage, type FeedbackCategory } from './model'
import { useSendFeedbackMutation } from './queries'

const MESSAGE_MAX = 1000

/**
 * 서비스 피드백 시트(#10). 계정 시트·지도 정보에서 연다. 지도 안에서 열면 그 지도 id를 맥락으로 같이 보낸다.
 * 답장은 없다고 미리 알린다 — 기다리게 하지 않는다.
 */
export default function FeedbackSheet({ mapId, onClose }: { mapId?: string; onClose: () => void }) {
  const send = useSendFeedbackMutation()
  const [category, setCategory] = useState<FeedbackCategory>('other')
  const [message, setMessage] = useState('')
  const ready = message.trim() !== ''

  function submit() {
    send.mutate(
      { message: message.trim(), category, ...(mapId ? { map_id: mapId } : {}) },
      {
        onSuccess: () => {
          showToast('의견을 보냈어요. 고마워요')
          onClose()
        },
      },
    )
  }

  return (
    <ModalSheet label="의견 보내기" onClose={onClose}>
      <SheetTitle>의견 보내기</SheetTitle>
      <p className="mb-4 mt-1 text-sm text-ink-500">불편했던 점이나 바라는 점을 알려 주세요. 답장은 드리지 않지만 모두 읽어요.</p>

      <div role="group" aria-label="분류" className="mb-3 flex gap-2">
        {FEEDBACK_CATEGORIES.map((c) => (
          <button key={c.key} type="button" aria-pressed={category === c.key} onClick={() => setCategory(c.key)} className="chip">
            {c.label}
          </button>
        ))}
      </div>

      <textarea
        aria-label="의견"
        value={message}
        maxLength={MESSAGE_MAX}
        onChange={(e) => setMessage(e.target.value)}
        placeholder="예: 핀을 지울 때 되돌리기가 있으면 좋겠어요"
        rows={5}
        className="field w-full resize-none py-3"
      />
      <p className="mt-1 text-right text-label text-ink-500">
        {message.length}/{MESSAGE_MAX}
      </p>

      {send.error && <ErrorText message={feedbackErrorMessage(send.error)} error={send.error} />}

      <button type="button" onClick={submit} disabled={!ready || send.isPending} className="btn-primary btn-lg mt-3 w-full">
        {send.isPending ? '보내는 중…' : '보내기'}
      </button>
    </ModalSheet>
  )
}
