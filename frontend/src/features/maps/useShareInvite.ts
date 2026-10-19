import { useEffect, useState } from 'react'

import { showToast } from '@/features/shell/toast'

import { useCreateInviteMutation, useMapQuery } from './queries'

/**
 * 이 지도의 초대 링크 공유·복사(프로필 모달, 온보딩). 공유 창이 없는 브라우저(데스크톱 대부분)는 복사로 대신한다.
 * 링크는 화면을 열 때 한 번 만든다(쓰기라 쿼리로 두지 않는다 — 이벤트로 지도 캐시가 무효화될 때마다 다시 만들던 문제, #442).
 * 누를 때 만들지 않는 건 iOS Safari 가 버튼을 누른 그 순간에만 공유 창을 열어 주기 때문이다. 서버는 내 유효한 링크를 재사용한다(#467).
 */
export function useShareInvite(mapId: string) {
  const invite = useCreateInviteMutation()
  const { mutate } = invite
  useEffect(() => mutate(mapId), [mapId, mutate])
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
