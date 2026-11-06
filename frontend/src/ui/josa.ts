/** 받침 있으면 첫째, 없으면 둘째 조사("대천 여행" + 을/를 → "을"). 한글이 아니면 받침 없는 쪽으로 본다. */
export function josa(word: string, withFinal: string, withoutFinal: string) {
  const code = word.charCodeAt(word.length - 1) - 0xac00
  return code >= 0 && code <= 11171 && code % 28 !== 0 ? withFinal : withoutFinal
}


/** 「으로/로」. ㄹ 받침은 받침이 없을 때처럼 「로」다("서울로", "장현성으로"). */
export function josaRo(word: string) {
  const code = word.charCodeAt(word.length - 1) - 0xac00
  return code >= 0 && code <= 11171 && code % 28 !== 0 && code % 28 !== 8 ? '으로' : '로'
}
