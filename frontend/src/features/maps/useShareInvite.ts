import { useState } from 'react'

import { showToast } from '@/features/shell/toast'

import { useInviteQuery, useMapQuery } from './queries'

/**
 * 이 지도의 초대 링크 공유·복사(프로필 모달, AI 탭 '준비 전'). 공유 창이 없는 브라우저(데스크톱 대부분)는 복사로 대신한다.
 * `enabled` 가 켜질 때 링크를 받는다 — 화면을 열 때마다 링크를 새로 만들지 않게 한 번 받은 건 기억한다.
 */
export function useShareInvite(mapId: string, enabled = true) {
  const invite = useInviteQuery(mapId, enabled)
  const title = useMapQuery(mapId).data?.title
  const [copied, setCopied] = useState(false)
  const url = invite.data?.url

  async function copy() {
    if (!url) return
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      showToast('초대 링크를 복사했어요')
    } catch (err) {
      console.error('[invite] 링크 복사 실패', err)
      showToast('링크를 복사하지 못했어요. 길게 눌러 직접 복사해 주세요')
    }
  }

  async function share() {
    if (!url) return
    if (!navigator.share) return copy()
    try {
      await navigator.share({ title, url })
    } catch (err) {
      // 사용자가 공유 창을 닫은 건 실패가 아니다.
      if (err instanceof DOMException && err.name === 'AbortError') return
      console.error('[invite] 공유 실패', err)
      void copy()
    }
  }

  return { url, error: invite.error, copied, copy, share }
}
