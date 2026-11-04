import { CircleHelp } from 'lucide-react'

import MenuPopover from '@/features/shell/MenuPopover'
import Mark from '@/ui/Mark'

/** 처음 보는 사람이 묻는 말(#1030, 멘토 리뷰 #816). 용어는 기획안 9절 고정이라 바꾸지 않고 뜻만 적는다. */
const TERMS = [
  { mark: (
      <span className="text-[var(--good-line)]">
        <Mark kind="like" size={14} />
      </span>
    ), term: '좋음', text: '가고 싶은 곳이에요' },
  {
    mark: (
      <span className="text-[var(--bad-line)]">
        <Mark kind="against" size={14} />
      </span>
    ),
    term: '반대',
    text: '가기 어려운 곳이에요. 남긴 이유로 AI가 다른 곳을 찾아요',
  },
  { mark: (
      <span className="text-ink-500">
        <Mark kind="unknown" size={14} />
      </span>
    ), term: '미확인', text: '아직 의견을 남기지 않은 사람 수예요' },
  {
    mark: <span className="text-[var(--pin-confirmed-mark)]">
        <Mark kind="star" size={14} />
      </span>,
    term: '확정 리스트',
    text: '가기로 정한 곳이에요. 확정된 장소 탭에서 들를 순서를 봐요',
  },
]

/**
 * 좋음·반대·미확인·확정 리스트가 무엇인지 그 말이 나오는 자리(핀 상세 집계 줄, 마킹된 장소 목록 머리)에서 연다.
 * 「미확인」은 장소 정보가 확인 안 됐다는 말로 읽히기 쉬워서, 아직 의견을 남기지 않은 사람 수라는 걸 여기서 푼다.
 */
export default function ReactionHelp() {
  return (
    <MenuPopover
      label="의견 표시 설명"
      trigger={
        <button type="button" aria-label="좋음, 반대, 미확인 설명 보기" className="btn-text inline-flex shrink-0 items-center">
          <CircleHelp size={16} aria-hidden="true" />
        </button>
      }
    >
      <dl className="space-y-2.5 text-body">
        {TERMS.map((t) => (
          <div key={t.term} className="flex gap-2">
            <dt className="flex w-24 shrink-0 items-center gap-1 font-bold text-ink-900">
              <span aria-hidden="true" className="flex w-4 justify-center">
                {t.mark}
              </span>
              {t.term}
            </dt>
            <dd className="break-keep text-ink-700">{t.text}</dd>
          </div>
        ))}
      </dl>
    </MenuPopover>
  )
}
