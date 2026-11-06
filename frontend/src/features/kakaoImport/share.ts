/**
 * 카톡 「대화 내보내기」 파일에서 지도 링크와 공유 글의 상호명·주소를 읽는다(#1046, 형식은 #1046 루트 코멘트의 실제 내보내기).
 * 사용자가 고른 기간(여행 얘기를 한 날짜, #1139)에 보낸 메시지만 읽는다.
 * 브라우저 안에서만 돌고, 대화 원문·보낸 사람·시각은 여기서 쓰고 버린다 — 돌려주는 것은 링크와 그 링크의 이름·주소뿐이다.
 *
 * 메시지 머리(시각·보낸 사람)는 내보내기·복사 방식마다 달라서 기대지 않는다. **링크 줄을 기준으로 위로 거꾸로** 읽는다.
 *   [네이버지도]                  ← 머리줄
 *   유소바 안국역점                ← 상호명
 *   서울 종로구 창덕궁1길 32 1층    ← 주소(시·도로 시작)
 *   https://naver.me/…            ← 링크
 *
 *   [카카오맵] 우슬               ← 머리줄에 상호명
 *   대전 중구 중앙로138번길 48 (대흥동)
 *   (빈 줄)
 *   https://kko.to/…
 *
 *   우슬 - https://maps.app.goo.gl/…      ← 구글: 「이름 - 링크」 한 줄
 *   [지도] 강남면옥 정동점 / (다음 메시지) https://maps.app.goo.gl/…   ← 구글: 이름과 링크가 따로
 */

export type Provider = 'naver' | 'kakao' | 'google'

export type Share = {
  /** 추적 파라미터만 걷어 낸 링크. 장소를 가리키는 값(id·itemId·pinId·query 등)은 그대로 둔다. */
  url: string
  provider: Provider
  /** 공유 글의 상호명. 못 읽으면 없다. */
  name?: string
  /** 공유 글의 주소(시·도로 시작하는 줄). 못 읽으면 없다. */
  address?: string
  /** 이름을 못 읽은 링크가 들어 있던 메시지의 다른 줄(링크 제외, 최대 2줄). 화면에서 사람이 알아보게 회색으로만 보인다 — 저장·전송하지 않는다. */
  context?: string[]
}

/**
 * 링크 없이 이름만 온 공유(카카오맵에서 채팅방으로 바로 보낸 카드는 내보내기에 「[지도] 이름」만 남는다).
 * 줄 구분값은 링크 대신 그 머리줄이다 — 서버에 링크로 보내지 않고 이름으로만 찾는다. 미리 체크하지 않는다.
 */
export const isNameOnly = (url: string) => !/^https?:\/\//i.test(url)
const NAME_ONLY = /^\[지도\]\s*\S/

/** 대화 하나에서 확인하는 링크 수(link-preview 설명의 50개). 화면 문구에는 이 숫자를 적지 않는다. */
export const LINK_MAX = 50

/**
 * 지도 링크. 네이버(#1048 — 서버가 단축 링크를 한 번 따라가 번호를 읽는다)·카카오·구글. 인스타·블로그는 잡지 않는다.
 * 구글: google.<도메인>/maps/…, maps.google.<도메인>/…, maps.app.goo.gl/…, goo.gl/maps/…
 */
const MAP_LINK =
  /https?:\/\/(?:naver\.me\/|(?:m\.)?map\.naver\.com\/|m\.place\.naver\.com\/|place\.map\.kakao\.com\/|map\.kakao\.com\/|kko\.to\/|maps\.app\.goo\.gl\/|goo\.gl\/maps\/|(?:www\.)?google\.[a-z.]+\/maps\/|maps\.google\.[a-z.]+\/)[^\s<>"']*/gi

/** 한 줄에 링크가 있는지만 볼 때(전역 플래그가 없어 lastIndex 가 남지 않는다). */
const HAS_LINK = new RegExp(MAP_LINK.source, 'i')

/** 대화 문장에서 링크 뒤에 붙는 문장부호는 링크가 아니다(「…/123).」). */
const TRAILING = /[).,!?…]+$/

/** 장소와 상관없는 추적 파라미터. 이것만 걷는다 — 쿼리 전체를 지우면 장소를 가리키는 값까지 사라진다. */
const TRACKING = /^(?:g_st|g_ep|utm_[a-z]+|fbclid|gclid|igshid|si)$/i

function providerOf(url: string): Provider {
  const host = url.replace(/^https?:\/\//i, '').split('/')[0].toLowerCase()
  if (host.endsWith('naver.me') || host.endsWith('naver.com')) return 'naver'
  if (host.endsWith('kakao.com') || host === 'kko.to') return 'kakao'
  return 'google'
}

export function normalizeUrl(raw: string): string {
  const url = raw.replace(TRAILING, '')
  try {
    const u = new URL(url)
    const drop = [...u.searchParams.keys()].filter((k) => TRACKING.test(k))
    if (drop.length === 0) return url
    for (const k of drop) u.searchParams.delete(k)
    return u.toString()
  } catch {
    return url
  }
}

/** 시·도 정식 이름 → 공유 글이 쓰는 줄임말. 주소 비교에도 쓴다. */
const SIDO_SHORT: Record<string, string> = {
  서울특별시: '서울',
  부산광역시: '부산',
  대구광역시: '대구',
  인천광역시: '인천',
  광주광역시: '광주',
  대전광역시: '대전',
  울산광역시: '울산',
  세종특별자치시: '세종',
  경기도: '경기',
  강원도: '강원',
  강원특별자치도: '강원',
  충청북도: '충북',
  충청남도: '충남',
  전라북도: '전북',
  전북특별자치도: '전북',
  전라남도: '전남',
  경상북도: '경북',
  경상남도: '경남',
  제주도: '제주',
  제주특별자치도: '제주',
}
const SIDO = new Set([...Object.values(SIDO_SHORT), ...Object.keys(SIDO_SHORT)])
export const shortSido = (token: string) => SIDO_SHORT[token] ?? token

/**
 * 주소 줄인가 — 첫 낱말이 시·도이고 다음 낱말이 시·군·구다(세종은 바로 도로명). 「서울숲 카페」 같은 상호를 주소로 읽지 않게 둘째 낱말까지 본다.
 */
export function isAddress(line: string): boolean {
  const [first, second] = line.trim().split(/\s+/)
  if (!first || !second || !SIDO.has(first)) return false
  return shortSido(first) === '세종' || /[시군구]$/.test(second)
}

/** 지도 앱 공유 글의 머리줄. 상호명이 붙어 오기도 한다(「[카카오맵] 우슬」). */
const SHARE_HEAD = /^\[(?:네이버\s?지도|카카오\s?맵|지도)\]\s*/

type Line = { text: string; sender?: string; at?: number; head: boolean }

/** 여행 얘기를 한 기간(#1139). `YYYY-MM-DD`, 양끝 포함. `to`가 없으면 파일 끝까지 읽는다. */
export type DayRange = { from: string; to?: string }

/** 메시지 하나와 보낸 날짜(`YYYY-MM-DD`). 파일 맨 앞 제목 줄처럼 첫 날짜보다 먼저 나온 줄은 날짜가 없다. */
type Message = { day?: string; lines: Line[] }

type Head = { sender: string; at: number; text: string; day?: string }

/**
 * 메시지 머리 — 내보내기(모바일·예전 형식)와 PC. 있으면 떼고, 보낸 사람·시각(분)은 구글 분리형 판단에만 쓴다.
 * 모바일·예전 형식 머리에는 날짜가 붙어 있고, PC 머리에는 시각만 있어 날짜는 구분선에서 읽는다.
 */
const HEADS: { re: RegExp; read: (m: RegExpMatchArray) => Head }[] = [
  {
    re: /^(\d{4})년 (\d{1,2})월 (\d{1,2})일 (오전|오후) (\d{1,2}):(\d{2}), (.+?) : (.*)$/,
    read: (m) => ({ sender: m[7], at: minutes(+m[1], +m[2], +m[3], m[4], +m[5], +m[6]), text: m[8], day: dayOf(+m[1], +m[2], +m[3]) }),
  },
  {
    re: /^(\d{4})\. (\d{1,2})\. (\d{1,2})\. (오전|오후) (\d{1,2}):(\d{2}), (.+?) : (.*)$/,
    read: (m) => ({ sender: m[7], at: minutes(+m[1], +m[2], +m[3], m[4], +m[5], +m[6]), text: m[8], day: dayOf(+m[1], +m[2], +m[3]) }),
  },
  { re: /^\[(.+?)\] \[(오전|오후) (\d{1,2}):(\d{2})\] (.*)$/, read: (m) => ({ sender: m[1], at: minutes(0, 1, 1, m[2], +m[3], +m[4]), text: m[5] }) },
]
/** 날짜 구분선(모바일 「2026년 11월 2일 일요일」, PC 「--------------- 2026년 11월 2일 일요일 ---------------」). 메시지가 아니다. */
const SEPARATOR = /^(?:\d{4}년 \d{1,2}월 \d{1,2}일 \S+요일|-{3,}.*-{3,})$/
/** 구분선 안의 날짜 — 모바일·PC 구분선 둘 다 이 글자가 들어 있다. */
const SEPARATOR_DATE = /(\d{4})년 (\d{1,2})월 (\d{1,2})일/

function minutes(y: number, mo: number, d: number, ampm: string, h: number, mi: number): number {
  const h24 = (h % 12) + (ampm === '오후' ? 12 : 0)
  return Date.UTC(y, mo - 1, d, h24, mi) / 60000
}

const pad = (n: number) => String(n).padStart(2, '0')
const dayOf = (y: number, mo: number, d: number) => `${y}-${pad(mo)}-${pad(d)}`

function readHead(line: string): Head | null {
  for (const { re, read } of HEADS) {
    const m = line.match(re)
    if (m) return read(m)
  }
  return null
}

/**
 * 메시지로 묶는다 — 머리가 있는 줄이 새 메시지를 연다. 머리 없는 줄은 앞 메시지에 이어 붙는다.
 * 날짜는 구분선과 날짜가 붙은 머리가 바꾸고, 그 뒤 메시지(날짜 없는 PC 머리 포함)는 그 날짜를 따른다.
 */
function toMessages(text: string): Message[] {
  const messages: Message[] = []
  let day: string | undefined
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim()
    if (SEPARATOR.test(line)) {
      const m = line.match(SEPARATOR_DATE)
      if (m) day = dayOf(+m[1], +m[2], +m[3])
      // 구분선 뒤 머리 없는 줄이 앞 메시지에 붙지 않게 끊는다.
      messages.push({ day, lines: [] })
      continue
    }
    // 빈 줄은 담지 않는다(공유 글 안의 빈 줄도 위로 읽을 때 건너뛴다). 링크만 든 메시지를 알아보는 데 걸리지 않게.
    if (line === '') continue
    const head = readHead(line)
    if (head) {
      if (head.day) day = head.day
      messages.push({ day, lines: [{ text: head.text, sender: head.sender, at: head.at, head: true }] })
    } else if (messages.length === 0) messages.push({ day, lines: [{ text: line, head: false }] })
    else messages[messages.length - 1].lines.push({ text: line, head: false })
  }
  return messages.filter((m) => m.lines.length > 0)
}

const clean = (s: string, max: number) => {
  const t = s.replace(SHARE_HEAD, '').trim()
  return t && t.length <= max && !HAS_LINK.test(t) ? t : undefined
}

/** 링크 줄 위(같은 메시지, 빈 줄 건너뜀) 최대 3줄에서 주소와 상호명을 읽는다. */
function readAbove(above: string[]): { name?: string; address?: string } {
  const lines = above.filter((l) => l.trim() !== '').slice(-3).reverse()
  const at = lines.findIndex((l, i) => i < 2 && isAddress(l))
  if (at >= 0) {
    const nameLine = lines[at + 1]
    return { address: lines[at].trim().slice(0, 200), name: nameLine ? clean(nameLine, 100) : undefined }
  }
  const top = lines[0]
  // 「이름 주소」가 한 줄인 공유 글(카카오맵 링크 복사, 「성수동대림창고갤러리 서울 성동구 성수이로 78 1층」). 바로 위 줄만 본다.
  const words = top?.replace(SHARE_HEAD, '').trim().split(/\s+/) ?? []
  for (let i = 1; i < words.length - 1; i++) {
    const address = words.slice(i).join(' ')
    if (isAddress(address)) return { name: clean(words.slice(0, i).join(' '), 100), address: address.slice(0, 200) }
  }
  // 주소가 없어도 바로 위가 공유 머리줄에 상호명이 붙은 줄이면(구글 「[지도] 이름」) 이름만 읽는다.
  if (top && SHARE_HEAD.test(top)) return { name: clean(top, 100) }
  return {}
}

/**
 * 고른 기간(양끝 포함, 끝이 없으면 시작일부터 파일 끝까지)에 보낸 메시지만 남겨 지도 링크를 뽑고, 링크마다 공유 글의 상호명·주소를 읽는다. 날짜를 모르는 메시지는 뺀다.
 * 같은 링크는 한 번만, 나온 순서대로. 같은 링크가 여러 번이면 이름·주소를 읽은 쪽을 남긴다.
 * `found`는 중복을 뺀 전체 수, `shares`는 앞에서부터 LINK_MAX개, `dated`는 날짜를 하나라도 읽었는지다(내보내기 파일이 아니면 false).
 */
export function readShares(text: string, range: DayRange): { shares: Share[]; found: number; dated: boolean } {
  const byUrl = new Map<string, Share>()
  const all = toMessages(text)
  const messages = all.filter((m) => m.day !== undefined && m.day >= range.from && (!range.to || m.day <= range.to)).map((m) => m.lines)
  messages.forEach((message, mi) => {
    message.forEach((line, li) => {
      for (const m of line.text.matchAll(MAP_LINK)) {
        const url = normalizeUrl(m[0])
        const provider = providerOf(url)
        const share: Share = { url, provider }
        const before = line.text.slice(0, m.index).trim()
        if (before) {
          // 「이름 - 링크」 한 줄(구글)
          const dash = before.match(/^(.*\S)\s+-$/)
          if (dash) share.name = clean(dash[1], 100)
        } else {
          Object.assign(share, readAbove(message.slice(0, li).map((l) => l.text)))
        }
        // 구글: 링크만 있는 메시지면 바로 앞 메시지(같은 사람, 5분 안 — 알 수 있을 때만 본다)의 「[지도] 이름」.
        if (!share.name && provider === 'google' && li === 0 && message.length === 1 && line.text.trim() === m[0]) {
          const prev = messages[mi - 1]
          const head = prev?.[0]
          const sameSender = !head?.sender || !line.sender || head.sender === line.sender
          const close = head?.at == null || line.at == null || Math.abs(line.at - head.at) <= 5
          if (prev?.length === 1 && head && /^\[지도\]\s*\S/.test(head.text) && sameSender && close) share.name = clean(head.text, 100)
        }
        if (!share.name) {
          // 이름을 못 읽은 링크 — 같은 메시지의 다른 줄을 사람이 보고 알아보게 남긴다(최대 2줄, 링크 제외).
          const context = message
            .map((l) => l.text.replace(MAP_LINK, '').trim())
            .filter(Boolean)
            .slice(0, 2)
            .map((t) => t.slice(0, 80))
          if (context.length > 0) share.context = context
        }
        const seen = byUrl.get(url)
        if (!seen || (!seen.name && share.name)) byUrl.set(url, share)
      }
    })
  })
  // 링크가 없는 메시지의 「[지도] 이름」 — 구글 분리형처럼 다음 메시지 링크의 이름으로 이미 읽었으면 넣지 않는다.
  const linkedNames = new Set([...byUrl.values()].map((s) => s.name))
  for (const message of messages) {
    if (message.some((l) => HAS_LINK.test(l.text))) continue
    for (const line of message) {
      const name = NAME_ONLY.test(line.text) ? clean(line.text, 100) : undefined
      if (!name || linkedNames.has(name)) continue
      const key = `[지도] ${name}`
      if (!byUrl.has(key)) byUrl.set(key, { url: key, provider: 'kakao', name })
    }
  }
  const shares = [...byUrl.values()]
  return { shares: shares.slice(0, LINK_MAX), found: shares.length, dated: all.some((m) => m.day !== undefined) }
}
