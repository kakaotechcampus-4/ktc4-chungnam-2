import { api } from '@/api'

import type { CourseRunDto } from './model'

export const createCourse = (mapId: string, body: { request_text?: string }) =>
  api<{ course_run_id: string }>(`/maps/${mapId}/courses`, { method: 'POST', body: JSON.stringify(body) })

export const fetchCourseRun = (runId: string) => api<CourseRunDto>(`/course-runs/${runId}`)

/** 내 마지막 코스. 없으면 204 라서 null — react-query 는 undefined 를 data 로 받지 않는다. */
export const fetchLatestCourse = async (mapId: string) => (await api<CourseRunDto | undefined>(`/maps/${mapId}/courses/latest`)) ?? null
