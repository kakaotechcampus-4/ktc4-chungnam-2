import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { showToast } from '@/features/shell/toast'

import { claimAdSession, openAdSession } from './api'
import { AD_TEXT, adCreditedText, adErrorAction, type AdClaimDto, type CreditAdDto } from './model'
import { invalidateCredits } from './queries'
import { load, type LoadedAd } from './rewardedAd'

const wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, Math.max(0, ms)))

/** 광고 충전 요청이 실패해 흐름을 멈춘다. 오류 → 화면 행동(adErrorAction)은 이미 처리했다. */
class Stopped extends Error {}

/**
 * 광고 보고 충전(#1039, docs/credits-reviews.md 3.7)의 흐름. CreditGate 의 잔액 부족 안내가 쓴다.
 * - enabled(잔액 부족 안내가 떴다)이고 ad.available 이면 광고를 미리 불러 두고, 준비된 뒤에만 ready.
 * - start: 세션 열기 → 광고 → 끝까지 봤으면 claim_after_s 가 지날 때까지 기다림 → 받기 → 토스트 → onCharged.
 * - 하나가 도는 동안 busy — 버튼을 막아 같은 요청을 두 번 보내지 않는다.
 * 끝나면(성공·실패 모두) 크레딧을 다시 읽는다. available 이 꺼지면 버튼이 사라진다.
 */
export function useAdCharge({ ad, enabled, onCharged }: { ad?: CreditAdDto; enabled: boolean; onCharged?: () => void }) {
  const queryClient = useQueryClient()
  const [loaded, setLoaded] = useState<LoadedAd | null>(null)
  const [failed, setFailed] = useState(false)
  const [busy, setBusy] = useState(false)
  /** 광고는 한 번 보이면 끝이다 — 다시 누를 수 있게 이 값을 올려 새로 불러온다. */
  const [loadKey, setLoadKey] = useState(0)

  const wanted = enabled && ad?.available === true && !failed
  const provider = ad?.provider ?? null
  const unitId = ad?.unit_id ?? null

  useEffect(() => {
    if (!wanted) return
    let alive = true
    load(provider, unitId).then(
      (next) => alive && setLoaded(next),
      () => {
        if (!alive) return
        setFailed(true)
        showToast(AD_TEXT.loadFailed)
      },
    )
    return () => {
      alive = false
      setLoaded(null)
    }
  }, [wanted, provider, unitId, loadKey])

  /** 받기. too_early 면 retry_after_s 뒤 한 번만 다시 한다. */
  async function claim(id: string): Promise<AdClaimDto> {
    try {
      return await claimAdSession(id)
    } catch (err) {
      const action = adErrorAction(err)
      if (action.kind !== 'retry') throw report(err)
      await wait(action.afterS * 1000)
      try {
        return await claimAdSession(id)
      } catch (again) {
        throw report(again, true)
      }
    }
  }

  /** 오류를 화면 행동으로 바꿔 알리고 흐름을 멈춘다. */
  function report(err: unknown, retried = false) {
    const action = adErrorAction(err, { retried })
    if (action.kind === 'toast') showToast(action.message)
    return new Stopped()
  }

  async function start() {
    if (!loaded || busy) return
    setBusy(true)
    try {
      let session
      try {
        session = await openAdSession()
      } catch (err) {
        throw report(err)
      }
      const openedAt = Date.now()
      const outcome = await loaded.show({ seconds: session.claim_after_s })
      if (outcome === 'error') {
        setFailed(true)
        showToast(AD_TEXT.loadFailed)
        return
      }
      if (outcome === 'dismissed') {
        // 다시 누르면 서버가 같은 세션을 돌려준다(하루 횟수를 쓰지 않는다).
        showToast(AD_TEXT.dismissed)
        return
      }
      await wait(openedAt + session.claim_after_s * 1000 - Date.now())
      const res = await claim(session.ad_session_id)
      showToast(adCreditedText(res.credited))
      onCharged?.()
    } catch (err) {
      if (!(err instanceof Stopped)) showToast(AD_TEXT.failed)
    } finally {
      setBusy(false)
      setLoadKey((k) => k + 1)
      void invalidateCredits(queryClient)
    }
  }

  return { ready: wanted && loaded !== null, busy, start }
}
