import { useEffect, type ReactNode } from 'react'
import { AlertDialog } from 'radix-ui'

/**
 * 확인 창(Figma 근거 확인 계열·로그아웃). 포커스 가두기·Esc 닫기는 Radix AlertDialog 가 맡는다(#299·#359).
 * 고르게 하는 창이라 딤을 눌러도 닫히지 않는다. 빨강(danger)은 파괴적 동작(빼기)에만 쓴다.
 */
export default function ConfirmDialog({
  title,
  body,
  detail,
  note,
  children,
  cancel = '취소',
  ok,
  danger = false,
  pending = false,
  onCancel,
  onOk,
}: {
  title: string
  body: string
  /** 제목 아래 회색 상자에 담는 목록·표. */
  detail?: ReactNode
  note?: string
  /** 버튼 바로 위 — 실패 문구 같은 것. */
  children?: ReactNode
  cancel?: string
  ok: string
  danger?: boolean
  /** 확인을 누른 뒤 처리 중이면 확인 버튼을 막는다. */
  pending?: boolean
  onCancel: () => void
  onOk: () => void
}) {
  // 부모가 통째로 빼서 닫으므로 Radix 의 닫힘 복귀가 돌지 않는다(ModalSheet 와 같은 이유). 연 버튼으로 직접 돌려준다.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    return () => opener?.focus()
  }, [])

  return (
    <AlertDialog.Root open onOpenChange={(open) => !open && onCancel()}>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="fixed inset-0 z-50 bg-scrim" />
        <AlertDialog.Content className="fixed inset-0 z-50 flex items-center justify-center p-6 outline-none">
          <div className="w-full max-w-sm space-y-2 rounded-2xl bg-white p-5">
            <AlertDialog.Title className="text-lg font-bold text-ink-900">{title}</AlertDialog.Title>
            {detail && <div className="rounded-lg bg-ink-50 p-3 text-sm">{detail}</div>}
            <AlertDialog.Description className="text-sm text-ink-600">{body}</AlertDialog.Description>
            {note && <p className="text-xs text-ink-500">{note}</p>}
            {children}
            <div className="grid grid-cols-2 gap-2 pt-2">
              <AlertDialog.Cancel className="rounded-lg border border-ink-300 py-2.5 text-sm font-semibold">{cancel}</AlertDialog.Cancel>
              {/* AlertDialog.Action 은 누르자마자 닫혀서 쓰지 않는다 — 처리 중에도 창을 띄워 두는 곳이 있다(반경 넓히기). */}
              <button
                type="button"
                onClick={onOk}
                disabled={pending}
                className={`btn-primary py-2.5 text-sm ${danger ? 'bg-[var(--action-danger)]' : ''}`}
              >
                {ok}
              </button>
            </div>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  )
}
