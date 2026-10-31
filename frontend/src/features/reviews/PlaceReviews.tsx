import { useState } from 'react'

import ErrorText from '@/ErrorText'
import GuestAccountNotice from '@/features/auth/GuestAccountNotice'
import { creditBlock, guestCreditText, type CreditBlock } from '@/features/credits/model'
import { useCreditsQuery } from '@/features/credits/queries'
import { timeAgo, type Pin } from '@/features/map/model'
import { showToast } from '@/features/shell/toast'
import ConfirmDialog from '@/ui/ConfirmDialog'
import StarRating from '@/ui/StarRating'

import { authorLabel, flattenPages, summaryText, type ReviewItemDto } from './model'
import { useDeleteReviewMutation, useReportReviewMutation, useReviewsQuery } from './queries'
import ReviewSheet from './ReviewSheet'

/**
 * 핀 상세의 장소 후기(#953). 자체 DB 장소 핀에만 둔다(hasReviews). 후기는 지도가 아니라 장소에 붙어서
 * 같은 장소의 다른 지도 후기도 보인다. 작성자는 「나」/「핑고 사용자」뿐이다(#432 결정 B).
 * 후기는 SNS가 아니다(결정 C) — 댓글·좋아요·프로필을 붙이지 않는다.
 * 게스트는 목록만 본다. 게스트임은 #952 와 같이 GET /credits/me 의 403 으로 안다(숫자도 그 detail 에서).
 */
export default function PlaceReviews({ pin }: { pin: Pin }) {
  const reviews = useReviewsQuery(pin.id)
  const credits = useCreditsQuery()
  const report = useReportReviewMutation()
  const [writing, setWriting] = useState(false)
  const [reported, setReported] = useState<Set<string>>(() => new Set())
  const [asking, setAsking] = useState<{ kind: 'delete' } | { kind: 'report'; item: ReviewItemDto } | null>(null)
  const guest = guestOf(creditBlock(credits.error)) ?? guestOf(creditBlock(report.error))

  if (reviews.isPending) return null
  // 「더 보기」가 실패해도 받은 쪽은 남긴다 — 처음부터 못 받았을 때만 이 줄 하나다.
  if (!reviews.data) return <ErrorText message="후기를 불러오지 못했어요" error={reviews.error} />

  const { summary, limits, mine, items } = flattenPages(reviews.data.pages)
  const name = pin.place_name ?? '이 장소'

  function sendReport(item: ReviewItemDto) {
    report.mutate(item.id, {
      onSuccess: () => {
        setReported((s) => new Set(s).add(item.id))
        setAsking(null)
        showToast('신고했어요')
      },
      onError: (err) => {
        setAsking(null)
        if (!creditBlock(err)) showToast('신고하지 못했어요')
      },
    })
  }

  return (
    <section aria-labelledby="place-reviews" className="space-y-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <h3 id="place-reviews" className="text-sm font-bold text-ink-900">
            장소 후기
          </h3>
          <p className="mt-0.5 flex items-center gap-1.5 text-body text-ink-700">
            {summary.average_rating !== null && <StarRating value={summary.average_rating} />}
            {summaryText(summary)}
          </p>
        </div>
        {!guest && (
          <button type="button" onClick={() => setWriting(true)} className="btn-outline btn-sm shrink-0">
            {mine ? '내 후기 고치기' : '후기 쓰기'}
          </button>
        )}
      </div>

      {guest && <GuestAccountNotice>{guestCreditText(guest.initialCredits)}</GuestAccountNotice>}

      {items.length > 0 && (
        <ul className="divide-y divide-ink-200 overflow-hidden rounded-xl bg-ink-50">
          {items.map((item) => (
            <li key={item.id} className="space-y-1 p-3">
              <div className="flex items-center gap-1.5 text-xs text-ink-500">
                <span className="font-bold text-ink-900">{authorLabel(item)}</span>
                <StarRating value={item.rating} />
                <span>· {timeAgo(item.created_at)}</span>
                {item.is_mine ? (
                  <button type="button" onClick={() => setAsking({ kind: 'delete' })} className="btn-text ml-auto">
                    삭제
                  </button>
                ) : (
                  !guest && (
                    <button
                      type="button"
                      disabled={reported.has(item.id)}
                      onClick={() => setAsking({ kind: 'report', item })}
                      className="btn-text ml-auto"
                    >
                      {reported.has(item.id) ? '신고함' : '신고'}
                    </button>
                  )
                )}
              </div>
              <p className="whitespace-pre-line break-words text-body text-ink-900">{item.body}</p>
            </li>
          ))}
        </ul>
      )}

      {reviews.hasNextPage && (
        <div className="flex justify-center">
          <button type="button" onClick={() => void reviews.fetchNextPage()} disabled={reviews.isFetchingNextPage} className="btn-link text-body">
            {reviews.isFetchingNextPage ? '불러오는 중…' : '더 보기'}
          </button>
        </div>
      )}
      {reviews.isFetchNextPageError && <ErrorText message="후기를 더 불러오지 못했어요" error={reviews.error} />}

      {writing && <ReviewSheet pinId={pin.id} placeName={name} bodyMax={limits.body_max} mine={mine} onClose={() => setWriting(false)} />}
      {asking?.kind === 'delete' && <DeleteMine pinId={pin.id} onDone={() => setAsking(null)} />}
      {asking?.kind === 'report' && (
        <ConfirmDialog
          title="이 후기를 신고할까요?"
          body="욕설이나 장소와 상관없는 글이면 알려 주세요. 운영자가 확인해요."
          ok="신고"
          pending={report.isPending}
          onCancel={() => setAsking(null)}
          onOk={() => sendReport(asking.item)}
        />
      )}
    </section>
  )
}

const guestOf = (block: CreditBlock | null) => (block?.kind === 'guest' ? block : null)

/** 내 후기 지우기. 받은 크레딧은 그대로이고 다시 써도 다시 받지 않는다(api-spec DELETE /pins/{pinId}/reviews/me). */
function DeleteMine({ pinId, onDone }: { pinId: string; onDone: () => void }) {
  const del = useDeleteReviewMutation(pinId)
  return (
    <ConfirmDialog
      title="내 후기를 지울까요?"
      body="받은 크레딧은 그대로예요. 다시 써도 크레딧을 다시 받지는 않아요."
      ok="삭제"
      danger
      pending={del.isPending}
      onCancel={onDone}
      onOk={() =>
        del.mutate(undefined, {
          onSuccess: () => {
            showToast('후기를 지웠어요')
            onDone()
          },
          onError: () => showToast('후기를 지우지 못했어요'),
        })
      }
    />
  )
}
