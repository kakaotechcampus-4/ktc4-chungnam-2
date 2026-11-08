import type { MatcherFunction } from '@testing-library/react'

/**
 * 여러 문장이 줄마다 나뉜 글(ui/Sentences)을 원래 문장 그대로 찾는다.
 * 기본 getByText 는 한 요소의 바로 아래 글자만 보므로, 문장 줄이 나뉘면 찾지 못한다.
 */
export const wholeText =
  (text: string): MatcherFunction =>
  (_, el) =>
    el?.textContent === text && !Array.from(el.children).some((child) => child.textContent === text)
