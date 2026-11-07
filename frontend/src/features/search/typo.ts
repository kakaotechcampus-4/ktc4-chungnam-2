/**
 * 장소 검색 0곳일 때 「혹시 이걸 찾으셨나요?」를 고른다(「중곡집」 → 「중국집」).
 * 서버 검색은 오타를 고치지 않는다. 사람 이름·가게 이름은 사전에 없으니 고치지 않고,
 * 자주 치는 음식·장소 종류 말만 자모 한 개(긴 말은 두 개) 차이까지 고친다. 바꿔 검색하지 않고 제안만 한다.
 */
// ponytail: 손으로 고른 낱말 목록. 고치지 못하는 검색어가 쌓이면 서버 검색어 기록에서 다시 고른다.
const WORDS = [
  // 음식 종류
  '중국집', '중식', '한식', '일식', '양식', '분식', '횟집', '고깃집', '술집', '국밥', '순대국', '감자탕', '해장국',
  '칼국수', '냉면', '짜장면', '짬뽕', '탕수육', '마라탕', '훠궈', '양꼬치', '삼겹살', '갈비', '곱창', '막창',
  '족발', '보쌈', '치킨', '피자', '햄버거', '파스타', '스테이크', '초밥', '스시', '라멘', '우동', '돈까스',
  '돈가스', '덮밥', '김밥', '떡볶이', '쌀국수', '카레', '샤브샤브', '닭갈비', '닭볶음탕', '삼계탕', '부대찌개',
  '김치찌개', '된장찌개', '순두부', '비빔밥', '백반', '한정식', '오마카세', '이자카야', '포장마차', '브런치',
  '베이커리', '빵집', '디저트', '케이크', '아이스크림', '빙수', '카페', '커피', '와인바', '맥주', '호프',
  // 가 볼 곳
  '관광지', '박물관', '미술관', '전시', '공원', '시장', '전통시장', '야경', '전망대', '한옥마을', '해수욕장',
  '산책로', '서점', '놀이공원', '수족관', '동물원',
  // 숙소
  '숙소', '호텔', '게스트하우스', '펜션', '모텔',
]

/** 한글 음절을 초성·중성·종성 번호로 푼다. 한글이 아닌 글자는 그대로 한 칸이다. */
function jamo(word: string): string[] {
  return [...word].flatMap((ch) => {
    const c = ch.charCodeAt(0) - 0xac00
    if (c < 0 || c > 11171) return [ch]
    const t = c % 28
    return [`c${Math.floor(c / 588)}`, `v${Math.floor((c % 588) / 28)}`, ...(t ? [`t${t}`] : [])]
  })
}

function distance(a: string[], b: string[]): number {
  let prev = b.map((_, j) => j + 1)
  prev.unshift(0)
  for (let i = 1; i <= a.length; i++) {
    const cur = [i]
    for (let j = 1; j <= b.length; j++) {
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1))
    }
    prev = cur
  }
  return prev[b.length]
}

const HANGUL_WORD = /^[가-힣]{2,}$/

function fixWord(word: string): string {
  if (!HANGUL_WORD.test(word) || WORDS.includes(word)) return word
  const w = jamo(word)
  const limit = word.length >= 4 ? 2 : 1
  let best = word
  let bestD = limit + 1
  for (const cand of WORDS) {
    if (Math.abs(cand.length - word.length) > 1) continue
    const d = distance(w, jamo(cand))
    if (d < bestD) [best, bestD] = [cand, d]
  }
  return best
}

/** 고칠 낱말이 하나라도 있으면 고친 검색어, 없으면 null. 「성수 중곡집」 → 「성수 중국집」. */
export function suggestQuery(query: string): string | null {
  const fixed = query.trim().split(/\s+/).map(fixWord).join(' ')
  return fixed !== query.trim() ? fixed : null
}
