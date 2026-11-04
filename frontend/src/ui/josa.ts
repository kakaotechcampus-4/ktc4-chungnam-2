/** 숫자를 한국어로 읽을 때 받침이 있는 끝자리(영·일·삼·육·칠·팔). */
const DIGIT_FINAL = '013678'

/**
 * 받침 있으면 첫째, 없으면 둘째 조사("대천 여행" + 을/를 → "을").
 * 끝의 괄호·따옴표·공백은 건너뛰고(「식당(본관)」 → 「관」), 숫자는 읽는 소리로 본다(「카페 1」 → 「일」).
 * 그 밖에 한글이 아니면 받침 없는 쪽으로 본다.
 */
export function josa(word: string, withFinal: string, withoutFinal: string) {
  const last = word.replace(/[\s)\]}'"」』〉》.,!?…]+$/u, '').slice(-1)
  if (/[0-9]/.test(last)) return DIGIT_FINAL.includes(last) ? withFinal : withoutFinal
  const code = last.charCodeAt(0) - 0xac00
  return code >= 0 && code <= 11171 && code % 28 !== 0 ? withFinal : withoutFinal
}
