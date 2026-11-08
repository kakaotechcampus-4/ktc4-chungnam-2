import { beforeEach, describe, expect, it } from 'vitest'

import { useToastStore } from '@/features/shell/toast'

import { GUEST_NUDGE_TEXT, nudgeGuestOnce } from './guestNudge'

describe('nudgeGuestOnce', () => {
  beforeEach(() => {
    localStorage.clear()
    useToastStore.setState({ toast: null })
  })

  it('게스트에게 이 브라우저에서 한 번만 권한다', () => {
    nudgeGuestOnce(true)
    expect(useToastStore.getState().toast?.message).toBe(GUEST_NUDGE_TEXT)
    useToastStore.setState({ toast: null })
    nudgeGuestOnce(true)
    expect(useToastStore.getState().toast).toBeNull()
  })

  it('정식 계정에는 권하지 않는다', () => {
    nudgeGuestOnce(false)
    nudgeGuestOnce(undefined)
    expect(useToastStore.getState().toast).toBeNull()
  })
})
