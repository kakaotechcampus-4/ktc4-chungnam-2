import { Fragment } from 'react'

/** 문장 끝(마침표·물음표·느낌표·줄임표) 뒤 공백에서 나눈다. 「10.10」처럼 공백이 없는 점은 나누지 않는다. */
export function splitSentences(text: string): string[] {
  return text.split(/(?<=[.?!…])\s+(?=\S)/)
}

/** 이 말로 끝나는 어절 뒤는 뜻이 한 번 끊긴다(「…탭에서 / 가고 싶은 곳들을 / 확정 리스트에 / 먼저 담아 보세요」). */
const PHRASE_END = /(,|·|에서|에게|으로|에는|에도|부터|까지|려면|으면|는데|지만|니까|도록|해서|이라|라서|에|면|고)$/
/** 을·를 뒤는 다음 말이 움직씨가 아닐 때만 끊는다 — 「곳들을 / 확정 리스트에」는 끊고 「핀을 / 남겨」는 붙인다. */
const OBJECT_END = /[을를]$/
const VERB_LIKE = /(요|다|해|고|서|며|면|지|게|어|아|여|워|러|라|혀|겨|켜|쳐|는|은|던|기|져|봐|줘|와|려|할|될|들|갈|볼|을|를)[.?!]?$/
/** 앞 어절과 떼면 안 되는 말 — 매인 이름씨(수·것·곳·때)와 도움 움직씨(있다·싶다·보다·주다). 「찾을 / 수 있어요」를 막는다. */
const BOUND_NEXT = /^(수|것|거|곳|때|줄|적|만큼|뿐|데|있|없|싶|보|봐|주|줘|드|않|못|말|하|해|돼|되|두|둬|놓|나|가요|와요|오)/
/** 이보다 짧은 덩어리는 이웃에 붙인다 — 「보여요」 한 마디가 따로 놀지 않게. 끝 덩어리는 더 길어야 한다(「… / 참여해요.」를 막는다). */
const MIN_PHRASE = 5
const MIN_LAST = 8
const ONE_LINE = 22

/**
 * 한 문장을 뜻 덩어리(구절)로 나눈다. 줄이 넘어가야 할 때 덩어리 사이에서만 넘어가게 하려는 것이다.
 * 한국어를 정확히 끊는 규칙이 아니라 조사·어미로 어림한다 — 틀려도 줄바꿈 자리가 하나 줄 뿐이다.
 */
export function splitPhrases(sentence: string): string[] {
  const words = sentence.split(/\s+/).filter(Boolean)
  const phrases: string[][] = [[]]
  words.forEach((word, i) => {
    phrases[phrases.length - 1].push(word)
    const next = words[i + 1]
    const ends = PHRASE_END.test(word) || (OBJECT_END.test(word) && !!next && !VERB_LIKE.test(next))
    if (next && ends && !BOUND_NEXT.test(next)) phrases.push([])
  })
  // 짧은 덩어리는 다음 덩어리에(마지막이면 앞 덩어리에) 붙인다.
  const merged: string[] = []
  for (let i = 0; i < phrases.length; i++) {
    let text = phrases[i].join(' ')
    while (text.length < MIN_PHRASE && i + 1 < phrases.length) text = `${text} ${phrases[++i].join(' ')}`
    if (text.length < MIN_PHRASE && merged.length) merged[merged.length - 1] += ` ${text}`
    else merged.push(text)
  }
  if (merged.length > 1 && merged[merged.length - 1].length < MIN_LAST) merged.push(`${merged.splice(-2, 2).join(' ')}`)
  return merged
}

/** 뜻 덩어리마다 한 덩이로 — 넘어갈 때는 덩어리 사이에서만 넘어간다. 덩어리가 칸보다 길면 그 안에서 줄을 바꾼다. */
function Phrases({ sentence }: { sentence: string }) {
  // 휴대폰 한 줄(13~14px로 약 24자)에 들어가는 짧은 문장은 넘어갈 일이 없어 그대로 둔다.
  if (sentence.length <= ONE_LINE) return sentence
  const phrases = splitPhrases(sentence)
  if (phrases.length < 2) return sentence
  // 덩어리 사이 공백은 덩어리 밖에 둔다 — inline-block 안 끝 공백은 그려지지 않아 「탭에서가고」처럼 붙는다.
  return phrases.map((phrase, i) => (
    <Fragment key={i}>
      <span className="inline-block">{phrase}</span>
      {i < phrases.length - 1 && ' '}
    </Fragment>
  ))
}

/**
 * 안내 글의 줄바꿈(DESIGN.md 「문장마다 줄」, #1511).
 * - 두 문장 이상이면 문장마다 줄을 바꾼다. 이어 쓰면 「결과는 나에게만 / 보여요」처럼 끝말만 떨어진다.
 * - 한 문장이 칸보다 길면 뜻 덩어리 사이에서 넘어간다. 「…확정 리스트에 먼저 / 담아 보세요」 대신
 *   「…가고 싶은 곳들을 / 확정 리스트에 먼저 담아 보세요」.
 * 글자는 그대로 둔다 — 문장·덩어리 사이 공백을 남겨 복사·읽어 주기가 원래 글과 같다.
 */
export default function Sentences({ text }: { text: string }) {
  // 서버 문구가 비어 오는 경우(알 수 없는 결과 종류 등) — 감싸기 전처럼 아무것도 그리지 않는다.
  if (!text) return null
  const parts = splitSentences(text)
  if (parts.length < 2) return <Phrases sentence={text} />
  return parts.map((part, i) => (
    <span key={i} className="block">
      <Phrases sentence={part} />
      {i < parts.length - 1 && ' '}
    </span>
  ))
}
