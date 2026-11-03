import { afterEach, describe, expect, it } from 'vitest'

import { forgetSchedule } from './scheduleStore'

describe('예전 이 기기 저장 일정 정리 (#1172)', () => {
  afterEach(() => window.localStorage.clear())

  it('일정이 서버로 옮겨 갔으므로 예전 키는 읽지 않고, 지도를 잊으면 그 지도 것만 지운다. 로그아웃(전체)은 모두 지운다', () => {
    window.localStorage.setItem('pingo.schedule.v1.m1', '{"days":{}}')
    window.localStorage.setItem('pingo.schedule.v1.m2', '{"days":{}}')
    window.localStorage.setItem('other', 'x')
    forgetSchedule('m1')
    expect(window.localStorage.getItem('pingo.schedule.v1.m1')).toBeNull()
    expect(window.localStorage.getItem('pingo.schedule.v1.m2')).not.toBeNull()
    forgetSchedule()
    expect(window.localStorage.getItem('pingo.schedule.v1.m2')).toBeNull()
    expect(window.localStorage.getItem('other')).toBe('x')
  })
})
