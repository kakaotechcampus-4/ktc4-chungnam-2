import { describe, expect, it } from 'vitest'

import { splitSentences } from './Sentences'

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
