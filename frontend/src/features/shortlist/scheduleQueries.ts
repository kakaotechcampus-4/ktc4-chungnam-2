import { useCallback, useMemo } from 'react'
import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'

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
 */
export const scheduleKeys = {
  one: (mapId: string) => [...shortlistKeys.list(mapId), 'schedule'] as const,
}

/**
 * 저장할 때 보낼 version — 저장이 없을 때 서버에서 **받은** 일정의 version이거나 내 저장이 성공해 돌려받은 값이다.
 * 내 저장이 서버에 가는 동안 받은 일정(다른 구성원의 변경일 수 있다)의 version은 쓰지 않는다: 그 변경을 보지 못한 채 만든 일정을
 * 그 version으로 보내면 409 없이 남의 변경을 덮는다. 그래서 저장 중에 받은 일정은 화면에 반영하지 않고(아래 `useScheduleQuery`),
 * 저장이 모두 끝난 뒤 다시 받는다.
 */
const versions = new Map<string, string>()
/** 아직 서버에 가지 못한 저장 수(지도별)와 이어 보내는 줄. */
const pending = new Map<string, number>()
const tails = new Map<string, Promise<void>>()
/** 앞 저장이 실패한 번호(지도별) — 그 뒤에 쌓인 저장은 실패한 고침을 품고 있어 보내지 않고 버린다. */
const epochs = new Map<string, number>()
/** 저장이 실패했거나 저장 중에 받은 일정을 버려서 서버 일정을 다시 받아야 하는 지도. */
const stale = new Set<string>()

export function useScheduleQuery(mapId: string) {
  const queryClient = useQueryClient()
  return useQuery({
    queryKey: scheduleKeys.one(mapId),
    queryFn: async () => {
      const dto = await fetchSchedule(mapId)
      // 저장이 가는 중이면 받은 일정으로 화면과 version을 바꾸지 않는다(저장이 끝나면 다시 받는다).
      if ((pending.get(mapId) ?? 0) > 0) {
        stale.add(mapId)
        return queryClient.getQueryData<ScheduleDto>(scheduleKeys.one(mapId)) ?? dto
      }
      versions.set(mapId, dto.version)
      return dto
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
 * 화면의 일정을 서버 요청과 바로 보여 줄 새 서버 일정으로 바꾼다. 모든 확정 항목이 정확히 한 번 들어가야 해서, 일정에 없는 항목은
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

/** 지도의 일정 — 아직 받는 중이면 빈 일정이다(`useTripSchedule`의 `ready`로 구분한다). */
export function useSchedule(mapId: string): Schedule {
  const data = useScheduleQuery(mapId).data
  return useMemo(() => scheduleFromDto(data), [data])
}

/** 지금 화면의 일정(React 밖 — 토스트의 「되돌리기」가 누르는 순간의 일정에서 되돌린다). */
export const currentSchedule = (queryClient: QueryClient, mapId: string): Schedule =>
  scheduleFromDto(queryClient.getQueryData<ScheduleDto>(scheduleKeys.one(mapId)))

/**
 * 일정을 고친다. 화면에 먼저 반영하고(고른 자리에 바로 놓인다) 서버에 순서대로 보낸다 — 앞 요청이 끝나야 다음을 보내
 * version이 어긋나지 않는다. 실패하면 서버 일정을 다시 받아 되돌린다. 다른 구성원이 먼저 고쳤으면(409) 그렇다고 알린다.
 */
export function saveSchedule(queryClient: QueryClient, mapId: string, next: Schedule) {
  const key = scheduleKeys.one(mapId)
  const dto = queryClient.getQueryData<ScheduleDto>(key)
  if (!dto) return
  const { groups, items } = groupsFor(dto, next)
  queryClient.setQueryData<ScheduleDto>(key, { ...dto, items })
  pending.set(mapId, (pending.get(mapId) ?? 0) + 1)
  const epoch = epochs.get(mapId) ?? 0

  const send = async () => {
    try {
      if ((epochs.get(mapId) ?? 0) !== epoch) return // 앞 저장이 실패했다 — 그 고침을 품은 이 저장은 보내지 않는다
      const saved = await putSchedule(mapId, { version: versions.get(mapId) ?? dto.version, groups })
      versions.set(mapId, saved.version)
      // 이어서 보낼 저장이 남아 있으면 그 고침이 화면에 먼저 있으니 덮지 않는다.
      if ((pending.get(mapId) ?? 1) <= 1) queryClient.setQueryData<ScheduleDto>(key, saved)
    } catch (error) {
      epochs.set(mapId, epoch + 1)
      versions.delete(mapId)
      stale.add(mapId)
      showToast(
        error instanceof ApiError && error.code === 'SHORTLIST_STALE'
          ? '다른 구성원이 일정을 먼저 바꿨어요. 최신 일정으로 다시 보여 드릴게요'
          : '일정을 저장하지 못했어요. 잠시 뒤 다시 해 주세요',
      )
    } finally {
      const left = Math.max(0, (pending.get(mapId) ?? 1) - 1)
      pending.set(mapId, left)
      // 저장이 모두 끝났다 — 실패했거나 저장 중 받지 못한 일정이 있을 수 있으니 서버 일정을 다시 받아 맞춘다.
      if (left === 0 && stale.delete(mapId)) void queryClient.invalidateQueries({ queryKey: key })
    }
  }
  tails.set(mapId, (tails.get(mapId) ?? Promise.resolve()).then(send))
}

/** 일정 고치기 함수 — `useScheduleEdit`과 화면이 쓴다. */
export function useSaveSchedule(mapId: string) {
  const queryClient = useQueryClient()
  return useCallback((next: Schedule) => saveSchedule(queryClient, mapId, next), [queryClient, mapId])
}
