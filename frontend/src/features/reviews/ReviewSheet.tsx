import { useState } from 'react'

import ErrorText from '@/ErrorText'
import GuestAccountNotice from '@/features/auth/GuestAccountNotice'
import { creditBlock, guestCreditText } from '@/features/credits/model'
import ModalSheet from '@/features/shell/ModalSheet'
import { showToast } from '@/features/shell/toast'
import SheetTitle from '@/ui/SheetTitle'
import StarRating from '@/ui/StarRating'

import { canSave, saveErrorMessage, savedText, type MyReviewDto } from './model'
import { useSaveReviewMutation } from './queries'

/**
 * 후기 쓰기·고치기 시트(#953). 내 후기가 있으면 그 값으로 열어 고친다. 글 상한은 응답의 limits.body_max 다(숫자를 적지 않는다).
 * 크레딧은 별점과 상관없이 같다고 미리 알린다(docs/credits-reviews.md 5절 사전 고지).
 */
export default function ReviewSheet({
  pinId,
  placeName,
  bodyMax,
  mine,
  onClose,
}: {
  pinId: string
  placeName: string
  bodyMax: number
  mine?: MyReviewDto
  onClose: () => void
}) {
  const save = useSaveReviewMutation(pinId)
  const [rating, setRating] = useState<number | null>(mine?.rating ?? null)
  const [body, setBody] = useState(mine?.body ?? '')
  const guest = creditBlock(save.error)

  function submit() {
    if (rating === null) return
    save.mutate(
      { rating, body: body.trim() },
      {
        onSuccess: (saved) => {
          showToast(savedText(saved))
          onClose()
        },
      },
    )
  }

  const title = mine ? '내 후기 고치기' : '후기 쓰기'
  return (
    <ModalSheet label={title} onClose={onClose}>
      <SheetTitle>{title}</SheetTitle>
      <p className="mt-1 text-sm text-ink-500">{placeName}</p>
      <p className="mb-3 mt-3 rounded-xl bg-ink-50 p-3 text-body text-ink-700">후기를 쓰면 크레딧을 드려요. 별점과 상관없이 같아요.</p>

      <StarRating value={rating} onChange={setRating} size={28} label="별점 고르기" />

      <textarea
        aria-label="후기"
        value={body}
        maxLength={bodyMax}
        onChange={(e) => setBody(e.target.value)}
        placeholder="다녀온 느낌을 적어 주세요"
        rows={5}
        className="field mt-3 w-full resize-none py-3"
      />
      <p className="mt-1 text-right text-label text-ink-500">
        {body.length}/{bodyMax}
      </p>

      {guest?.kind === 'guest' ? (
        <div className="mt-3">
          <GuestAccountNotice>{guestCreditText(guest.initialCredits)}</GuestAccountNotice>
        </div>
      ) : (
        save.error && <ErrorText message={saveErrorMessage(save.error)} error={save.error} />
      )}

      <button type="button" onClick={submit} disabled={!canSave(rating, body) || save.isPending} className="btn-primary btn-lg mt-3 w-full">
        {save.isPending ? '저장하는 중…' : '저장'}
      </button>
    </ModalSheet>
  )
}
