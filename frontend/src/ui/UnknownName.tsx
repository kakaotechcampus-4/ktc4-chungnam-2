import { Fragment } from 'react'

/** 누군지 모르는 사람(탈퇴한 작성자)의 이름 자리. */
export const UNKNOWN_NAME = '(알 수 없음)'

/** text 안의 「(알 수 없음)」만 흐리게 보인다. 이름이 아니라 빈자리라 다른 글자와 같은 색이면 이름처럼 읽힌다. */
export default function UnknownName({ text }: { text: string }) {
  return text.split(UNKNOWN_NAME).map((part, i) => (
    <Fragment key={i}>
      {i > 0 && <span className="text-ink-400">{UNKNOWN_NAME}</span>}
      {part}
    </Fragment>
  ))
}
