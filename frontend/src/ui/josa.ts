/** 숫자를 한국어로 읽을 때 받침이 있는 끝자리(영·일·삼·육·칠·팔). */
const DIGIT_FINAL = '013678'
/** 그중 ㄹ 받침이 아닌 끝자리(영·삼·육) — 「으로」를 붙인다. */
const DIGIT_FINAL_NOT_RIEUL = '036'

/** 조사를 고를 끝 글자. 끝의 괄호·따옴표·공백은 건너뛴다(「식당(본관)」 → 「관」). */
function lastChar(word: string) {
  return word.replace(/[\s)\]}'"」』〉》.,!?…]+$/u, '').slice(-1)
}

/** 한글 끝 글자의 받침 번호(없으면 0). 한글이 아니면 -1. */
function finalOf(ch: string) {
  const code = ch.charCodeAt(0) - 0xac00
  return code >= 0 && code <= 11171 ? code % 28 : -1
}

/**
 * 받침 있으면 첫째, 없으면 둘째 조사("대천 여행" + 을/를 → "을").
 * 끝의 괄호·따옴표·공백은 건너뛰고, 숫자는 읽는 소리로 본다(「카페 1」 → 「일」).
 * 그 밖에 한글이 아니면 받침 없는 쪽으로 본다.
 */
export function josa(word: string, withFinal: string, withoutFinal: string) {
  const last = lastChar(word)
  if (/[0-9]/.test(last)) return DIGIT_FINAL.includes(last) ? withFinal : withoutFinal
  return finalOf(last) > 0 ? withFinal : withoutFinal
}

/** 「으로/로」. ㄹ 받침은 받침이 없을 때처럼 「로」다("서울로", "장현성으로"). */
export function josaRo(word: string) {
  const last = lastChar(word)
  if (/[0-9]/.test(last)) return DIGIT_FINAL_NOT_RIEUL.includes(last) ? '으로' : '로'
  const final = finalOf(last)
  return final > 0 && final !== 8 ? '으로' : '로'
}
