import { create } from 'zustand'

export type ToastAction = { label: string; onClick: () => void }
type Toast = { id: number; message: string; action?: ToastAction; leaving: boolean }

type ToastState = {
  toast: Toast | null
  show: (message: string, action?: ToastAction) => void
  dismiss: (id: number) => void
}

/** Figma '토스트 (자동으로 사라짐)' — 3초, 되돌리기 같은 동작이 있으면 5초 뒤 0.3초 동안 흐려지며 사라진다. */
const TOAST_MS = { plain: 3000, withAction: 5000, fade: 300 }

let nextId = 0
let timers: ReturnType<typeof setTimeout>[] = []

/**
 * 한 번에 하나만 띄운다. 새 토스트가 오면 이전 것을 덮는다.
 * 타이머를 컴포넌트가 아니라 여기 두는 이유: 토스트를 그리는 자리(시트·모달)가 화면을 옮기며
 * 다시 마운트되면 타이머가 처음부터 다시 돌아 토스트가 사라지지 않는다.
 */
export const useToastStore = create<ToastState>((set) => ({
  toast: null,
  show: (message, action) => {
    timers.forEach(clearTimeout)
    const id = ++nextId
    const ms = action ? TOAST_MS.withAction : TOAST_MS.plain
    set({ toast: { id, message, action, leaving: false } })
    timers = [
      setTimeout(() => set((s) => (s.toast?.id === id ? { toast: { ...s.toast, leaving: true } } : s)), ms),
      setTimeout(() => set((s) => (s.toast?.id === id ? { toast: null } : s)), ms + TOAST_MS.fade),
    ]
  },
  dismiss: (id) => set((s) => (s.toast?.id === id ? { toast: null } : s)),
}))

export const showToast = (message: string, action?: ToastAction) => useToastStore.getState().show(message, action)
