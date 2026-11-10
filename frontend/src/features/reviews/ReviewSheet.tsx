import { useState } from 'react'

import ErrorText from '@/ErrorText'
import GuestAccountNotice from '@/features/auth/GuestAccountNotice'
import { creditBlock, guestCreditText, reviewRewardText, showsReviewReward } from '@/features/credits/model'
import { useCreditsQuery } from '@/features/credits/queries'
import ModalSheet from '@/features/shell/ModalSheet'
import { showToast } from '@/features/shell/toast'
import SheetTitle from '@/ui/SheetTitle'
import StarRating from '@/ui/StarRating'
import TextArea from '@/ui/TextArea'
import BusyLabel from '@/ui/BusyLabel'

import { canSave, RATING_WORDS, saveErrorMessage, type MyReviewDto } from './model'
import { useSaveReviewMutation } from './queries'

/**
 * 후기 쓰기·고치기 시트(#953). 내 후기가 있으면 그 값으로 열어 고친다. 글 상한은 응답의 limits.body_max 다(숫자를 적지 않는다).
 * 크레딧 문구는 새 후기 작성 시트에만 한 줄이다(docs/credits-reviews.md 5절 「화면 문구」). 고치기 시트와 저장 토스트에는 없다 —
 * 받은 양(credited)은 보이지 않는다. 잔액이 가득 차 보상이 0이면 그 줄도 숨긴다(판정은 showsReviewReward).
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
  const credits = useCreditsQuery()
  const [rating, setRating] = useState<number | null>(mine?.rating ?? null)
  const [body, setBody] = useState(mine?.body ?? '')
  const guest = creditBlock(save.error)

  function submit() {
    if (rating === null) return
    save.mutate(
      { rating, body: body.trim() },
      {
        onSuccess: () => {
          showToast('후기를 저장했어요')
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
      {!mine && showsReviewReward(credits.data) && <p className="mt-3 rounded-xl bg-ink-50 p-3 text-body text-ink-700">{reviewRewardText(credits.data?.review_reward)}</p>}

      {/* 별 옆에 고른 점수의 말 — 바뀌면 화면 읽기도 읽는다. */}
      <div className="mt-3 flex items-center gap-2">
        <StarRating value={rating} onChange={setRating} size={28} label="별점 고르기" />
        <p aria-live="polite" className={`text-sm ${rating === null ? 'text-ink-500' : 'font-bold text-link'}`}>
          {rating === null ? '별을 눌러 골라 주세요' : RATING_WORDS[rating - 1]}
        </p>
      </div>

      <TextArea
        label="후기"
        value={body}
        onChange={setBody}
        maxLength={bodyMax}
        placeholder="다녀온 느낌을 적어 주세요"
        rows={5}
        clearLabel="후기 지우기"
        className="mt-3"
      />

      {guest?.kind === 'guest' ? (
        <div className="mt-3">
          <GuestAccountNotice>{guestCreditText(guest.initialCredits)}</GuestAccountNotice>
        </div>
      ) : (
        save.error && <ErrorText message={saveErrorMessage(save.error)} error={save.error} />
      )}

      <button aria-busy={save.isPending} type="button" onClick={submit} disabled={!canSave(rating, body) || save.isPending} className="btn-primary btn-lg mt-3 w-full">
        <BusyLabel busy={save.isPending} busyText="저장하는 중…">저장</BusyLabel>
      </button>
    </ModalSheet>
  )
}
