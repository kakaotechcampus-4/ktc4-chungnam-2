import type { ImportRow } from './model'
import type { Provider } from './share'

/**
 * 카톡 가져오기 목록을 새로고침 뒤에도 잇는다(#1045). 지도별로 sessionStorage 에 둔다 — 새로고침은 넘기고 탭을 닫으면 사라진다.
 * 저장하는 것은 링크와 공유 글의 이름·주소, 사람이 고른 장소의 id(카카오 장소 ID는 저장이 허용된 값), 체크·찍음 결과뿐이다.
 * **대화 원문과 같이 온 말(`context`), 서버·카카오 응답(장소 이름·좌표·주소)은 저장하지 않는다**(#53, livePlaces 와 같은 원칙) —
 * 되살릴 때 미리보기와 이름 검색을 다시 해서 받는다. 저장소가 막혀 있어도(시크릿 창·차단) 저장 없이 그대로 동작한다.
 */
export type SavedRow = {
  url: string
  provider: Provider
  name?: string
  address?: string
  picked: boolean
  /** 사람이(또는 주소로 미리) 고른 장소. 서버가 찾은 곳(matches)은 다시 받으니 두지 않는다. */
  choiceId?: string
  outcome?: ImportRow['outcome']
  opened?: boolean
}

const PREFIX = 'pingo.kakaoImport.v1.'
const keyOf = (mapId: string) => `${PREFIX}${mapId}`

function storage(): Storage | null {
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

export function toSaved(row: ImportRow): SavedRow {
  const { url, provider, name, address } = row.share
  return {
    url,
    provider,
    ...(name ? { name } : {}),
    ...(address ? { address } : {}),
    picked: row.picked,
    ...(row.choice ? { choiceId: row.choice.place_id } : {}),
    ...(row.outcome ? { outcome: row.outcome } : {}),
    ...(row.opened ? { opened: true } : {}),
  }
}

/** 되살린 줄 — 서버 응답은 비어 있어 미리보기·이름 검색을 다시 한다. 고른 장소는 응답이 오면 `choiceId`로 다시 맞춘다. */
export function fromSaved(s: SavedRow): ImportRow {
  return {
    share: { url: s.url, provider: s.provider, ...(s.name ? { name: s.name } : {}), ...(s.address ? { address: s.address } : {}) },
    picked: s.picked,
    ...(s.choiceId ? { choiceId: s.choiceId } : {}),
    ...(s.outcome ? { outcome: s.outcome } : {}),
    ...(s.opened ? { opened: true } : {}),
  }
}

export function saveImport(mapId: string, rows: ImportRow[]) {
  const s = storage()
  if (!s) return
  try {
    if (rows.length === 0) s.removeItem(keyOf(mapId))
    else s.setItem(keyOf(mapId), JSON.stringify({ v: 1, rows: rows.map(toSaved) }))
  } catch {
    // 가득 찼거나 막혔다 — 저장 없이 이어 간다(목록은 화면 메모리에 그대로 있다).
  }
}

export function loadImport(mapId: string): ImportRow[] {
  const s = storage()
  if (!s) return []
  try {
    const raw = s.getItem(keyOf(mapId))
    if (!raw) return []
    const data = JSON.parse(raw) as { v?: number; rows?: SavedRow[] }
    if (data.v !== 1 || !Array.isArray(data.rows)) return []
    return data.rows.filter((r) => typeof r?.url === 'string' && typeof r?.provider === 'string').map(fromSaved)
  } catch {
    return []
  }
}

/** 지도 하나(지도 나가기·삭제) 또는 전부(로그아웃)를 지운다. */
export function clearImport(mapId?: string) {
  const s = storage()
  if (!s) return
  try {
    if (mapId) return s.removeItem(keyOf(mapId))
    for (const key of Object.keys(s)) if (key.startsWith(PREFIX)) s.removeItem(key)
  } catch {
    // 막혀 있으면 지울 것도 없다.
  }
}
