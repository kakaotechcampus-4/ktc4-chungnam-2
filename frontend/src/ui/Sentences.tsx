/** 문장 끝(마침표·물음표·느낌표·줄임표) 뒤 공백에서 나눈다. 「10.10」처럼 공백이 없는 점은 나누지 않는다. */
export function splitSentences(text: string): string[] {
  return text.split(/(?<=[.?!…])\s+(?=\S)/)
}

/**
 * 두 문장 이상인 안내 글은 문장마다 줄을 바꾼다(DESIGN.md 「문장마다 줄」, #1511).
 * 이어 쓰면 둘째 문장의 끝말만 다음 줄로 떨어져(「결과는 나에게만 / 보여요」) 읽는 단위가 흐트러진다.
 * 한 문장이면 글자 그대로 돌려준다.
 */
export default function Sentences({ text }: { text: string }) {
  // 서버 문구가 비어 오는 경우(알 수 없는 결과 종류 등) — 감싸기 전처럼 아무것도 그리지 않는다.
  if (!text) return null
  const parts = splitSentences(text)
  if (parts.length < 2) return text
  // 줄은 나눠도 글자는 그대로 둔다 — 문장 사이 공백을 남겨 복사·읽어 주기가 원래 문장과 같다.
  return parts.map((part, i) => (
    <span key={i} className="block">
      {i < parts.length - 1 ? `${part} ` : part}
    </span>
  ))
}
