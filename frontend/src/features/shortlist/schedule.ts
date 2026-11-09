/**
 * 확정 탭의 일정 — 확정된 장소를 여행 날짜에 나눠 순서대로 둔다(2026-11-03, 화면만). 시간은 정하지 않는다(범위 밖).
 * 그날 순서가 곧 「동선 보기」의 순서다. 어느 날에도 없는 장소는 확정 리스트에 남는다(따로 적어 두지 않는다).
 * 장소는 **날짜**에 붙는다. 여행 날짜를 고치면 새 기간에서 빠진 날에 넣은 장소만 확정 리스트로 돌아가고,
 * 남은 날의 장소는 그대로다(11/1~3 → 11/2~4 면 11/1 의 장소만 빠진다).
 */
export type Schedule = {
  /** 날짜(`YYYY-MM-DD`) → 그날 넣은 핀 id. 넣은 순서가 곧 순서다. 빈 날은 키가 없다. */
  days: Record<string, string[]>
}

export const EMPTY_SCHEDULE: Schedule = { days: {} }

/** 확정 리스트(일정에서 빼기)를 가리키는 칸 값. 날짜(`YYYY-MM-DD`)와 겹치지 않는다. */
export const UNSET_DAY = 'unset'

/** 끌어 놓을 자리 — 칸(날짜 또는 `UNSET_DAY`)과 그 칸 안에서 끼울 순서. */
export type DropSpot = { day: string; index: number }

/**
 * 손가락·마우스 밑의 놓을 자리. 칸은 `data-day`로, 칸 안의 줄은 `data-pin`으로 찾는다. 칸 밖이면 null.
 * 끄는 줄(`dragging`)은 빼고, 손가락보다 아래에 가운데가 있는 첫 줄 앞이 끼울 자리다(없으면 끝).
 * 「일정 짜기」 패널 카드, 「동선 보기」 그날 줄, 넓은 화면 확정 리스트 줄의 ≡가 같이 쓴다.
 */
export function dropSpot(x: number, y: number, dragging?: string): DropSpot | null {
  const box = document.elementFromPoint?.(x, y)?.closest<HTMLElement>('[data-day]')
  const day = box?.dataset.day
  if (!box || !day) return null
  const rows = [...box.querySelectorAll<HTMLElement>('[data-pin]')].filter((r) => r.dataset.pin !== dragging)
  const at = rows.findIndex((r) => {
    const b = r.getBoundingClientRect()
    return y < b.top + b.height / 2
  })
  return { day, index: at === -1 ? rows.length : at }
}

/** 여행 날짜 목록(양끝 포함). 날짜가 없거나 거꾸로면 빈 목록. */
export function tripDays(start: string | undefined, end: string | undefined): string[] {
  if (!start || !end || start > end) return []
  const out: string[] = []
  const d = new Date(`${start}T00:00:00Z`)
  for (let day = start; day <= end; day = d.toISOString().slice(0, 10)) {
    out.push(day)
    d.setUTCDate(d.getUTCDate() + 1)
  }
  return out
}

/** 그 핀을 넣은 날. 어느 날에도 없으면 null(확정 리스트에 있다). */
export function dayOf(schedule: Schedule, pinId: string): string | null {
  for (const [day, ids] of Object.entries(schedule.days)) if (ids.includes(pinId)) return day
  return null
}

/** 일정에 넣은 핀 전부. 확정 리스트는 이것을 뺀 나머지를 보인다. */
export function scheduledIds(schedule: Schedule): Set<string> {
  return new Set(Object.values(schedule.days).flat())
}

/**
 * 핀들을 그날 `index` 자리에 차례로 끼운다(없으면 끝). 다른 날이나 같은 날 다른 자리에 있었으면 옮긴다 — 같은 날이면 순서 바꾸기다.
 * `index`는 옮기는 핀을 뺀 그날 목록에서의 자리다(`dropSpot`과 같다). `day`가 null 이면 일정에서 빼 확정 리스트로 돌린다.
 */
export function place(schedule: Schedule, pinIds: string[], day: string | null, index?: number): Schedule {
  const moving = new Set(pinIds)
  const days: Record<string, string[]> = {}
  for (const [d, ids] of Object.entries(schedule.days)) {
    const rest = ids.filter((id) => !moving.has(id))
    if (rest.length > 0) days[d] = rest
  }
  if (day) {
    const list = days[day] ?? []
    const at = index === undefined ? list.length : Math.max(0, Math.min(index, list.length))
    days[day] = [...list.slice(0, at), ...pinIds, ...list.slice(at)]
  }
  return { days }
}

/** 「동선 보기」로 볼 날. 고른 날이 기간 안이면 그날, 아니면 장소를 넣은 첫 날, 그것도 없으면 첫 날. 날짜가 없으면 null. */
export function routeDay(schedule: Schedule, dates: string[], chosen: string | null): string | null {
  if (chosen && dates.includes(chosen)) return chosen
  return dates.find((d) => (schedule.days[d]?.length ?? 0) > 0) ?? dates[0] ?? null
}

/** 여행 날짜를 `from`에서 `to`로 고치면 빠지는 날(지금 기간 안, 새 기간 밖)에 넣어 둔 장소 수. 지도 정보 수정 창이 미리 알린다. */
export function droppedCount(schedule: Schedule, from: string[], to: string[]): number {
  const before = new Set(from)
  const after = new Set(to)
  let n = 0
  for (const [day, ids] of Object.entries(schedule.days)) if (before.has(day) && !after.has(day)) n += ids.length
  return n
}

/** 이 고침으로 마지막 빈 날이 채워지는지(#1723, 컨페티). 하루짜리 여행은 첫 장소로 바로 채워져서 치지 않는다. */
export function fillsLastDay(before: Schedule, next: Schedule, dates: string[]): boolean {
  const full = (s: Schedule) => dates.every((d) => s.days[d]?.length)
  return dates.length > 1 && !full(before) && full(next)
}
