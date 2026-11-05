import { describe, expect, it } from 'vitest'

import { DAYS_SAMPLE, EXPORT_SAMPLE, PC_DAYS_SAMPLE, PC_SAMPLE } from './__fixtures__/kakaotalkExport'
import { isAddress, LINK_MAX, normalizeUrl, readShares } from './share'

/** 픽스처 대화가 오간 날(2026-11-02) 하루. */
const DAY = { from: '2026-11-02', to: '2026-11-02' }

describe('카톡 대화에서 링크와 공유 글 읽기(#1046)', () => {
  const { shares, found } = readShares(EXPORT_SAMPLE, DAY)
  const by = (url: string) => shares.find((s) => s.url.startsWith(url))

  it('지도 링크 8개(네이버 4·카카오 1·구글 3)를 빠짐없이 뽑고, 인스타 링크는 잡지 않는다', () => {
    expect(found).toBe(8)
    expect(shares.map((s) => s.provider)).toEqual(['naver', 'naver', 'naver', 'naver', 'kakao', 'google', 'google', 'google'])
    expect(shares.some((s) => s.url.includes('instagram'))).toBe(false)
  })

  it('네이버 공유 글은 머리줄 아래 상호명과 주소를 읽는다(주소 꼬리·정식 시·도 이름 포함)', () => {
    expect(by('https://naver.me/FvTH6o34')).toMatchObject({ name: '유소바 안국역점', address: '서울 종로구 창덕궁1길 32 1층' })
    expect(by('https://naver.me/IDkVeMFP')).toMatchObject({ name: '예시 우동집', address: '서울 종로구 북촌로 12-3 (가회동)' })
    expect(by('https://naver.me/5MvQEV3V')).toMatchObject({ name: '예시 치즈케이크', address: '서울특별시 종로구 계동길 45 1층 예시상호' })
    expect(by('https://naver.me/Fhur93HL')).toMatchObject({ name: '예시 북촌 쇼룸', address: '서울 종로구 북촌로5길 20 2층' })
  })

  it('카카오 공유 글은 머리줄에 붙은 상호명을 읽고, 주소와 링크 사이 빈 줄을 건너뛴다', () => {
    expect(by('https://kko.to/UPShtpIfbq')).toMatchObject({ provider: 'kakao', name: '우슬', address: '대전 중구 중앙로138번길 48 (대흥동)' })
  })

  it('이름과 주소가 한 줄인 카카오맵 공유 글도 나눠 읽는다(place.map.kakao.com 링크)', () => {
    const text = '2026년 11월 2일 오전 1:05, 도윤 : 성수동대림창고갤러리 서울 성동구 성수이로 78 1층\n\nhttps://place.map.kakao.com/1038283810'
    expect(readShares(text, DAY).shares[0]).toMatchObject({
      provider: 'kakao',
      name: '성수동대림창고갤러리',
      address: '서울 성동구 성수이로 78 1층',
    })
  })

  it('구글은 「이름 - 링크」 한 줄과, 바로 앞 메시지의 「[지도] 이름」을 이름으로 읽는다(주소는 없다)', () => {
    expect(by('https://maps.app.goo.gl/uezSZd')).toMatchObject({ name: '우슬' })
    expect(by('https://maps.app.goo.gl/uezSZd')?.address).toBeUndefined()
    expect(by('https://maps.app.goo.gl/tTvQ51')).toMatchObject({ name: '강남면옥 정동점' })
  })

  it('이름을 못 읽은 링크는 이름을 지어내지 않고, 같은 메시지의 다른 말을 알아보는 데만 남긴다', () => {
    const plain = by('https://maps.app.goo.gl/YHqvpz')!
    expect(plain.name).toBeUndefined()
    expect(plain.context).toEqual(['여기도'])
  })

  it('잡담 줄은 이름·주소가 되지 않는다 — 「서울 가면 …」은 시·군·구가 없어 주소가 아니다', () => {
    expect(isAddress('서울 가면 다들 몇 시에 일어나?')).toBe(false)
    expect(isAddress('서울숲 카페')).toBe(false)
    expect(isAddress('세종 한누리대로 2130')).toBe(true)
    expect(shares.every((s) => s.name !== '이번 주말 갈 곳들 보낼게')).toBe(true)
  })

  it('보낸 사람·시각·대화 원문은 돌려주지 않는다', () => {
    const text = JSON.stringify(shares)
    expect(text).not.toContain('친구A')
    expect(text).not.toContain('친구B')
    expect(text).not.toContain('오전 1:0')
  })

  it('추적 파라미터만 걷고 장소를 가리키는 값은 남긴다', () => {
    expect(by('https://maps.app.goo.gl/uezSZd')?.url).toBe('https://maps.app.goo.gl/uezSZdUCictVGi9o8')
    expect(normalizeUrl('https://map.kakao.com/?itemId=12345&utm_source=kakaotalk')).toBe('https://map.kakao.com/?itemId=12345')
    expect(normalizeUrl('https://m.place.naver.com/restaurant/1412566798?entry=pll')).toBe('https://m.place.naver.com/restaurant/1412566798?entry=pll')
    expect(normalizeUrl('https://www.google.com/maps/search/?api=1&query=우슬).')).toBe('https://www.google.com/maps/search/?api=1&query=우슬')
  })

  it('같은 링크가 여러 번 나오면 하나로, 이름을 읽은 쪽을 남긴다', () => {
    const twice = `2026년 11월 2일 오전 1:00, 친구A : https://naver.me/FvTH6o34\n${EXPORT_SAMPLE}`
    const again = readShares(twice, DAY).shares.filter((s) => s.url === 'https://naver.me/FvTH6o34')
    expect(again).toHaveLength(1)
    expect(again[0].name).toBe('유소바 안국역점')
  })

  it('PC 복사 형식(「[이름] [오전 1:01]」, 날짜 구분선)도 같게 읽는다', () => {
    const pc = readShares(PC_SAMPLE, DAY).shares
    expect(pc).toEqual([
      { url: 'https://naver.me/FvTH6o34', provider: 'naver', name: '유소바 안국역점', address: '서울 종로구 창덕궁1길 32 1층' },
      { url: 'https://maps.app.goo.gl/tTvQ51jTNdUvRpWJA', provider: 'google', name: '강남면옥 정동점' },
    ])
  })

  it('상한을 넘으면 앞에서부터 자르고 찾은 수는 그대로 센다', () => {
    const many = `2026년 11월 2일 오전 1:00, 친구A : ${Array.from({ length: LINK_MAX + 5 }, (_, i) => `https://kko.to/p${i}`).join(' ')}`
    const r = readShares(many, DAY)
    expect(r.shares).toHaveLength(LINK_MAX)
    expect(r.found).toBe(LINK_MAX + 5)
  })
})

describe('여행 얘기를 한 기간의 메시지만 읽기(#1139)', () => {
  const urls = (r: ReturnType<typeof readShares>) => r.shares.map((s) => s.url)

  it('종료일이 없으면 시작일부터 대화 끝까지 읽는다', () => {
    expect(urls(readShares(DAYS_SAMPLE, { from: '2026-11-01' }))).toEqual(['https://kko.to/UPShtpIfbq', 'https://naver.me/FvTH6o34', 'https://naver.me/nextTrip'])
  })

  it('모바일 내보내기 — 머리의 날짜로 거르고, 기간 밖 링크(지난·다음 여행)는 빠진다', () => {
    const r = readShares(DAYS_SAMPLE, { from: '2026-11-01', to: '2026-11-01' })
    expect(urls(r)).toEqual(['https://kko.to/UPShtpIfbq', 'https://naver.me/FvTH6o34'])
    expect(r.shares[0]).toMatchObject({ name: '우슬', address: '대전 중구 중앙로138번길 48 (대흥동)' })
    expect(r.dated).toBe(true)
  })

  it('기간 양끝 날짜를 포함한다', () => {
    expect(urls(readShares(DAYS_SAMPLE, { from: '2026-10-30', to: '2026-11-03' }))).toEqual([
      'https://naver.me/oldTrip',
      'https://kko.to/UPShtpIfbq',
      'https://naver.me/FvTH6o34',
      'https://naver.me/nextTrip',
    ])
  })

  it('PC 내보내기 — 머리에 날짜가 없어 구분선의 날짜로 거른다', () => {
    const r = readShares(PC_DAYS_SAMPLE, { from: '2026-11-01', to: '2026-11-02' })
    expect(r.shares).toEqual([{ url: 'https://kko.to/UPShtpIfbq', provider: 'kakao', name: '우슬', address: '대전 중구 중앙로138번길 48 (대흥동)' }])
  })

  it('기간에 링크가 없으면 비어 있지만 날짜는 읽었다', () => {
    const r = readShares(DAYS_SAMPLE, { from: '2026-10-01', to: '2026-10-02' })
    expect(r.shares).toEqual([])
    expect(r.dated).toBe(true)
  })

  it('날짜가 하나도 없는 글(내보내기 파일이 아님)은 dated 가 false 이고 링크를 읽지 않는다', () => {
    const r = readShares('여기 가자 https://kko.to/abc\n[네이버지도]\n유소바 안국역점\nhttps://naver.me/FvTH6o34', { from: '2000-01-01', to: '2999-12-31' })
    expect(r.dated).toBe(false)
    expect(r.shares).toEqual([])
  })
})
