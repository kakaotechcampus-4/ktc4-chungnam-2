import { create } from 'zustand'

export type ToastAction = { label: string; onClick: () => void }
type Toast = { id: number; message: string; action?: ToastAction }

type ToastState = {
  toast: Toast | null
  show: (message: string, action?: ToastAction) => void
  dismiss: (id: number) => void
}

/** Figma '토스트 (자동으로 사라짐)' — 3초, 되돌리기 같은 동작이 있으면 5초 뒤 사라진다. */
export const TOAST_MS = { plain: 3000, withAction: 5000 }

let nextId = 0

/** 한 번에 하나만 띄운다. 새 토스트가 오면 이전 것을 덮는다. */
export const useToastStore = create<ToastState>((set) => ({
  toast: null,
  show: (message, action) => set({ toast: { id: ++nextId, message, action } }),
  dismiss: (id) => set((s) => (s.toast?.id === id ? { toast: null } : s)),
}))

export const showToast = (message: string, action?: ToastAction) => useToastStore.getState().show(message, action)
