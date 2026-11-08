import { CircleHelp } from 'lucide-react'

import MenuPopover from '@/features/shell/MenuPopover'
import Mark from '@/ui/Mark'
import Sentences from '@/ui/Sentences'

const CONFIRMED_MARK = (
  <span className="text-[var(--pin-confirmed-mark)]">
    <Mark kind="star" size={14} />
  </span>
)

/** 처음 보는 사람이 묻는 말(#1030, 멘토 리뷰 #816). 용어는 기획안 9절 고정이라 바꾸지 않고 뜻만 적는다. */
const PIN_TERMS = [
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
  { mark: CONFIRMED_MARK, term: '확정 리스트', text: '가기로 정한 곳이에요. 확정된 장소 탭에서 들를 순서를 봐요' },
]

/** 확정된 장소 탭에서 처음 보는 말(멘토 리뷰 #1401, #1484). */
const SHORTLIST_TERMS = [
  { mark: CONFIRMED_MARK, term: '확정 리스트', text: '가기로 정한 곳이에요. 아래 목록은 아직 일정에 넣지 않은 곳이에요' },
  // 글 옆 기호에 lucide를 쓰지 않아서(DESIGN.md Don't) 일정·동선 보기는 기호 없이 자리만 맞춘다.
  { mark: null, term: '일정', text: '날짜마다 들를 곳과 순서예요. 목록의 「넣기」로 고른 날에 넣어요' },
  { mark: null, term: '동선 보기', text: '일정에 넣은 순서대로 그날 길을 지도에 그려요' },
]

const VARIANTS = {
  pins: { terms: PIN_TERMS, label: '의견 표시 설명', button: '좋음, 반대, 미확인 설명 보기' },
  shortlist: { terms: SHORTLIST_TERMS, label: '확정 리스트와 일정 설명', button: '확정된 장소 탭 용어 설명 보기' },
}

/**
 * 용어가 무엇인지 그 말이 나오는 자리에서 연다. `pins`(기본): 핀 상세 집계 줄, 마킹된 장소 목록 머리. `shortlist`: 확정된 장소 탭 머리.
 * 「미확인」은 장소 정보가 확인 안 됐다는 말로 읽히기 쉬워서, 아직 의견을 남기지 않은 사람 수라는 걸 여기서 푼다.
 */
export default function ReactionHelp({ on = 'pins' }: { on?: keyof typeof VARIANTS }) {
  const { terms, label, button } = VARIANTS[on]
  return (
    <MenuPopover
      label={label}
      trigger={
        <button type="button" aria-label={button} className="btn-text inline-flex shrink-0 items-center">
          <CircleHelp size={16} aria-hidden="true" />
        </button>
      }
    >
      <dl className="space-y-2.5 text-body">
        {terms.map((t) => (
          <div key={t.term} className="flex gap-2">
            <dt className="flex w-24 shrink-0 items-center gap-1 font-bold text-ink-900">
              <span aria-hidden="true" className="flex w-4 justify-center">
                {t.mark}
              </span>
              {t.term}
            </dt>
            <dd className="break-keep text-ink-700">
              <Sentences text={t.text} />
            </dd>
          </div>
        ))}
      </dl>
    </MenuPopover>
  )
}
