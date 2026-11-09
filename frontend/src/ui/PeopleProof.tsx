import Avatar from './Avatar'

/** 겹쳐 그리는 얼굴 수. 넘치면 「+N」 원 하나로 줄인다. */
const MAX_FACES = 4

/**
 * 「누가 했는지」를 얼굴로 — 같은 지도의 구성원이 실제로 한 일만 보인다(DESIGN.md 「사람 표시」, #1547, 사회적 증거).
 * 이름 첫 글자 원을 겹치고, 옆에 「4명 중 2명이 의견을 남겼어요」처럼 숫자를 글로 꼭 적는다(얼굴만으로는 수가 안 읽힌다).
 * 아무도 안 했으면 얼굴 없이 글만이다. 지어낸 숫자나 지도 밖 사람 수는 쓰지 않는다.
 */
export default function PeopleProof({ names, total, verb }: { names: string[]; total: number; verb: string }) {
  const faces = names.slice(0, MAX_FACES)
  const rest = names.length - faces.length
  return (
    <p className="flex items-center gap-2 text-xs text-ink-600">
      {faces.length > 0 && (
        <span className="flex shrink-0" aria-hidden="true">
          {faces.map((name, i) => (
            <span key={`${name}-${i}`} className={`rounded-full ring-2 ring-white ${i > 0 ? '-ml-1.5' : ''}`}>
              <Avatar name={name} size={24} tone="brand" />
            </span>
          ))}
          {rest > 0 && (
            <span className="-ml-1.5 flex size-6 items-center justify-center rounded-full bg-ink-100 text-label font-semibold text-ink-600 ring-2 ring-white">+{rest}</span>
          )}
        </span>
      )}
      <span>
        {total}명 중 <b className="font-bold text-[var(--action-quiet-text)]">{names.length}명</b>
        {verb}
      </span>
    </p>
  )
}
