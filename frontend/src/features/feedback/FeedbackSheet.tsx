import { useState } from 'react'

import ErrorText from '@/ErrorText'
import ModalSheet from '@/features/shell/ModalSheet'
import { showToast } from '@/features/shell/toast'
import SegmentedControl from '@/ui/SegmentedControl'
import SheetTitle from '@/ui/SheetTitle'
import TextArea from '@/ui/TextArea'
import Sentences from '@/ui/Sentences'

import { FEEDBACK_CATEGORIES, feedbackErrorMessage, type FeedbackCategory } from './model'
import { useSendFeedbackMutation } from './queries'

const MESSAGE_MAX = 1000

/**
 * 서비스 피드백 시트(#10). 계정 시트·지도 정보에서 연다. 지도 안에서 열면 그 지도 id를 맥락으로 같이 보낸다.
 * 답장은 없다고 미리 알린다 — 기다리게 하지 않는다.
 */
export default function FeedbackSheet({
  mapId,
  onClose,
  initialCategory = 'other',
}: {
  mapId?: string
  onClose: () => void
  /** ☰ 메뉴 「버그 신고하기」는 버그를 골라 둔 채 연다(#1538). 창 제목도 따라 바뀐다. */
  initialCategory?: FeedbackCategory
}) {
  const send = useSendFeedbackMutation()
  const [category, setCategory] = useState<FeedbackCategory>(initialCategory)
  const bug = category === 'bug'
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
    <ModalSheet label={bug ? '버그 신고하기' : '의견 보내기'} onClose={onClose}>
      <SheetTitle>{bug ? '버그 신고하기' : '의견 보내기'}</SheetTitle>
      <p className="mb-4 mt-1 text-sm text-ink-500">
        <Sentences text="불편했던 점이나 바라는 점을 알려 주세요. 답장은 못 드리지만 모두 읽어요." />
      </p>

      <SegmentedControl label="분류" options={FEEDBACK_CATEGORIES} value={category} onChange={setCategory} className="mb-3" />

      <TextArea
        label="의견"
        value={message}
        onChange={setMessage}
        maxLength={MESSAGE_MAX}
        placeholder={bug ? '예: 핀 상세에서 의견을 쓰면 화면이 멈춰요. 언제, 어느 화면이었는지 적어 주세요' : '예: 핀을 지울 때 되돌리기가 있으면 좋겠어요'}
        rows={5}
        clearLabel="의견 지우기"
      />

      {send.error && <ErrorText message={feedbackErrorMessage(send.error)} error={send.error} />}

      <button type="button" onClick={submit} disabled={!ready || send.isPending} className="btn-primary btn-lg mt-3 w-full">
        {send.isPending ? '보내는 중…' : '보내기'}
      </button>
    </ModalSheet>
  )
}
