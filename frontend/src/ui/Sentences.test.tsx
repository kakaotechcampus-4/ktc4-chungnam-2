import { describe, expect, it } from 'vitest'

import { splitPhrases, splitSentences } from './Sentences'

describe('splitSentences', () => {
  it('마침표·물음표 뒤 공백에서 나눈다', () => {
    expect(splitSentences('확정된 장소를 날짜별로 나눠 순서를 짜 줘요. 결과는 나에게만 보여요')).toEqual([
      '확정된 장소를 날짜별로 나눠 순서를 짜 줘요.',
      '결과는 나에게만 보여요',
    ])
    expect(splitSentences('위치를 아직 찾지 못했어요. 다시 시도할까요?')).toHaveLength(2)
  })
  it('공백 없는 점(날짜·파일 이름)과 한 문장은 그대로', () => {
    expect(splitSentences('10.10 (토) ~ 10.12 (월)')).toEqual(['10.10 (토) ~ 10.12 (월)'])
    expect(splitSentences('.txt 파일을 넣어 주세요')).toEqual(['.txt 파일을 넣어 주세요'])
  })
})

describe('splitPhrases', () => {
  it('뜻 덩어리 사이에서만 넘어가게 나눈다', () => {
    expect(splitPhrases('마킹된 장소 탭에서 가고 싶은 곳들을 확정 리스트에 먼저 담아 보세요.')).toEqual([
      '마킹된 장소 탭에서',
      '가고 싶은 곳들을',
      '확정 리스트에',
      '먼저 담아 보세요.',
    ])
  })
  it('목적어와 움직씨, 매인 이름씨는 떼지 않는다', () => {
    expect(splitPhrases('지도에 핀을 남겨 함께 이야기를 나눌 수 있어요.')).toEqual(['지도에 핀을 남겨 함께 이야기를 나눌 수 있어요.'])
    expect(splitPhrases('게스트는 새 지도를 만들 수 없어요.')).toEqual(['게스트는 새 지도를 만들 수 없어요.'])
  })
  it('짧은 끝말은 앞 덩어리에 붙인다', () => {
    expect(splitPhrases('바로 그 지도에 참여해요.')).toEqual(['바로 그 지도에 참여해요.'])
  })
})
