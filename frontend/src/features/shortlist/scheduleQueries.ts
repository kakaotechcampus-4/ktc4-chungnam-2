import { useCallback, useMemo } from 'react'
import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { create } from 'zustand'

import { ApiError } from '@/api'
import { showToast } from '@/features/shell/toast'

import { fetchSchedule, putSchedule } from './api'
import type { ScheduleDto, ScheduleUpdateDto } from './model'
import { shortlistKeys } from './queries'
import { EMPTY_SCHEDULE, type Schedule } from './schedule'

/**
 * 확정 탭 일정의 서버 저장(#1172). 일정은 서버가 갖는다 — 구성원이 함께 보고 고친다. 화면은 핀 id로 다루고(`Schedule`),
 * 서버는 확정 항목 id로 받으므로(`ScheduleDto.items`) 바꿔 주는 일을 여기 한 곳에서 한다.
 * 키가 확정 리스트 키(`['shortlist', mapId]`) 아래라 `shortlist.changed`로 확정 리스트를 다시 받을 때 일정도 같이 다시 받는다.
 *
 * 상태는 둘뿐이다: ① 서버가 확인해 준 일정(쿼리 캐시) ② 아직 서버에 가지 않은 내 고침(`drafts`, 화면에 먼저 보인다).
 * 저장은 지도마다 한 번에 하나만 보낸다(`running`). 보낼 version은 항상 캐시의 것이고, 캐시는 내 저장이 성공했을 때와
 * 저장이 없을 때 받은 일정으로만 바뀐다 — 그래서 다른 구성원이 먼저 고쳤다면 서버가 409로 알려 준다(남의 변경을 덮지 않는다).
 */
export const scheduleKeys = {
  one: (mapId: string) => [...shortlistKeys.list(mapId), 'schedule'] as const,
}

/** 서버에 가지 않은 내 고침(지도별) — 화면은 이것을 서버 일정보다 먼저 보여 준다. 성공하면 비우고, 실패하면 버린다. */
const useDrafts = create<{ drafts: Record<string, Schedule | undefined> }>(() => ({ drafts: {} }))
const setDraft = (mapId: string, draft: Schedule | undefined) =>
  useDrafts.setState((s) => ({ drafts: { ...s.drafts, [mapId]: draft } }))
const getDraft = (mapId: string) => useDrafts.getState().drafts[mapId]

/** 저장을 보내는 중인 지도(지도별 하나의 약속) — 그동안은 일정 받기를 시작하지 않고 끝나길 기다린다. */
const running = new Map<string, Promise<void>>()
/** 저장이 시작되거나 끝날 때마다 오르는 번호(지도별) — 일정을 받는 동안 바뀌었으면 그 응답은 저장보다 앞선 것이라 다시 받는다. */
const generations = new Map<string, number>()
const bump = (mapId: string) => generations.set(mapId, (generations.get(mapId) ?? 0) + 1)

export function useScheduleQuery(mapId: string) {
  return useQuery({
    queryKey: scheduleKeys.one(mapId),
    queryFn: async () => {
      // 저장이 가는 중이면 끝나길 기다렸다가 받는다. 받는 동안 저장이 시작됐거나 끝났으면 그 응답은 낡았으니 다시 받는다(몇 번만, 그래도 겹치면 실패로 알린다).
      for (let attempt = 0; attempt < 3; attempt++) {
        await running.get(mapId)
        const started = generations.get(mapId) ?? 0
        const dto = await fetchSchedule(mapId)
        if ((generations.get(mapId) ?? 0) === started && !running.has(mapId)) return dto
      }
      // 저장이 계속 겹쳐 안전한 응답을 못 받았다 — 검사 없이 캐시에 넣지 않고 실패로 알려 다시 받게 한다.
      throw new Error('일정을 받는 동안 저장이 계속 겹쳤다')
    },
  })
}

const byOrder = (a: ScheduleDto['items'][number], b: ScheduleDto['items'][number]) =>
  (a.visit_order ?? Infinity) - (b.visit_order ?? Infinity)

/** 서버 일정 → 화면의 일정(날짜 → 핀 id, 그날 순서). 미배정은 담지 않는다(확정 리스트에 남는다). */
export function scheduleFromDto(dto: ScheduleDto | undefined): Schedule {
  if (!dto) return EMPTY_SCHEDULE
  const days: Record<string, string[]> = {}
  for (const item of [...dto.items].sort(byOrder)) {
    const day = item.scheduled_date
    if (day) (days[day] ??= []).push(item.pin.id)
  }
  return { days }
}

/**
 * 화면의 일정을 서버 요청 본문으로 바꾼다. 모든 확정 항목이 정확히 한 번 들어가야 해서, 일정에 없는 항목은
 * 미배정(`date: null`) 그룹에 지금 순서대로 모은다. 서버에 없는 핀 id는 건너뛴다.
 */
export function groupsFor(dto: ScheduleDto, next: Schedule): { groups: ScheduleUpdateDto['groups']; items: ScheduleDto['items'] } {
  const itemOf = new Map(dto.items.map((i) => [i.pin.id, i]))
  const used = new Set<string>()
  const groups: ScheduleUpdateDto['groups'] = []
  const items: ScheduleDto['items'] = []
  for (const day of Object.keys(next.days).sort()) {
    const dayItems = next.days[day].flatMap((pinId) => {
      const item = itemOf.get(pinId)
      if (!item || used.has(item.id)) return []
      used.add(item.id)
      return [item]
    })
    if (dayItems.length === 0) continue
    groups.push({ date: day, item_ids: dayItems.map((i) => i.id) })
    dayItems.forEach((item, order) => items.push({ ...item, scheduled_date: day, visit_order: order }))
  }
  const rest = [...dto.items].filter((i) => !used.has(i.id)).sort(byOrder)
  groups.push({ date: null, item_ids: rest.map((i) => i.id) })
  rest.forEach((item, order) => items.push({ ...item, scheduled_date: null, visit_order: order }))
  return { groups, items }
}

/** 지도의 일정 — 내 고침이 서버에 가는 중이면 그것을, 아니면 서버 일정을 보인다. 아직 받는 중이면 빈 일정이다(`useTripSchedule`의 `ready`로 구분). */
export function useSchedule(mapId: string): Schedule {
  const data = useScheduleQuery(mapId).data
  const draft = useDrafts((s) => s.drafts[mapId])
  return useMemo(() => draft ?? scheduleFromDto(data), [draft, data])
}

/** 지금 화면의 일정(React 밖 — 토스트의 「되돌리기」가 누르는 순간의 일정에서 되돌린다). */
export const currentSchedule = (queryClient: QueryClient, mapId: string): Schedule =>
  getDraft(mapId) ?? scheduleFromDto(queryClient.getQueryData<ScheduleDto>(scheduleKeys.one(mapId)))

/** 보내기 — 가장 최근 고침을 서버 일정(캐시)의 version으로 보낸다. 보내는 사이 더 고쳤으면 이어서 보낸다. 실패하면 고침을 버리고 서버 일정으로 돌아간다. */
async function flush(queryClient: QueryClient, mapId: string) {
  const key = scheduleKeys.one(mapId)
  try {
    for (let want = getDraft(mapId); want; want = getDraft(mapId)) {
      const base = queryClient.getQueryData<ScheduleDto>(key)
      if (!base) throw new Error('서버 일정을 아직 받지 못했다')
      const saved = await putSchedule(mapId, { version: base.version, groups: groupsFor(base, want).groups })
      queryClient.setQueryData<ScheduleDto>(key, saved)
      if (getDraft(mapId) === want) setDraft(mapId, undefined)
    }
  } catch (error) {
    setDraft(mapId, undefined)
    showToast(
      error instanceof ApiError && error.code === 'SHORTLIST_STALE'
        ? '다른 구성원이 먼저 일정을 바꿨어요. 바뀐 일정으로 다시 보여 줄게요'
        : '일정을 저장하지 못했어요. 잠시 뒤 다시 해 보세요',
    )
    void queryClient.invalidateQueries({ queryKey: key })
  }
}

/**
 * 일정을 고친다. 고침을 화면에 먼저 보이고(`drafts`) 서버에 보낸다. 서버 일정을 받기 전에는 아무것도 하지 않는다 —
 * 호출하는 쪽(`useScheduleEdit`)이 `ready`일 때만 부른다.
 */
export function saveSchedule(queryClient: QueryClient, mapId: string, next: Schedule) {
  if (!queryClient.getQueryData<ScheduleDto>(scheduleKeys.one(mapId))) return
  setDraft(mapId, next)
  if (running.has(mapId)) return // 보내는 중이면 그 루프가 이 고침을 이어서 보낸다
  bump(mapId)
  const job = flush(queryClient, mapId).finally(() => {
    running.delete(mapId)
    bump(mapId)
  })
  running.set(mapId, job)
}

/**
 * 저장 루프 밖에서 일정을 저장할 때(AI 코스 「반영」, #1322) 쓴다. 보내는 중인 저장이 끝나길 기다렸다가 보내고,
 * 앞뒤로 번호를 올려 그동안 받은 일정 응답이 저장한 일정을 덮지 않게 한다.
 */
export async function saveScheduleOutside<T>(mapId: string, save: () => Promise<T>): Promise<T> {
  await running.get(mapId)
  bump(mapId)
  try {
    return await save()
  } finally {
    bump(mapId)
  }
}

/** 일정 고치기 함수 — `useScheduleEdit`과 화면이 쓴다. */
export function useSaveSchedule(mapId: string) {
  const queryClient = useQueryClient()
  return useCallback((next: Schedule) => saveSchedule(queryClient, mapId, next), [queryClient, mapId])
}
