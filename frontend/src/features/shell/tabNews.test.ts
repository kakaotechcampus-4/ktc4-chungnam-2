import { renderHook } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'

import { clearTabNews, markTabNews, useTabNews } from './tabNews'

afterEach(() => {
  clearTabNews('m1', 'recommend')
  window.history.replaceState({}, '', '/')
})

const news = () => renderHook(() => useTabNews('m1', 'recommend')).result.current

it('다른 탭에 있으면 AI 추천 탭에 새 소식을 달고, 들어오면 지운다(#1704)', () => {
  window.history.replaceState({}, '', '/maps/m1/shortlist')
  markTabNews('m1', 'recommend', '음식점 추천 결과가 나왔어요')
  expect(news()).toBe('음식점 추천 결과가 나왔어요')
  clearTabNews('m1', 'recommend')
  expect(news()).toBeUndefined()
})

it('그 탭을 보고 있으면 달지 않는다 — 화면이 이미 결과로 바뀐다', () => {
  window.history.replaceState({}, '', '/maps/m1/recommend')
  markTabNews('m1', 'recommend', '음식점 추천 결과가 나왔어요')
  expect(news()).toBeUndefined()
})
