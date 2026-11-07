import { useEffect, useState } from 'react'
import { Dialog } from 'radix-ui'
import { X } from 'lucide-react'

/**
 * 테스트 광고 창 — 보상형 광고 자리를 대신하는 전체 화면 창(#1039, 제공자 fake). 실제 광고 스크립트는 없다.
 * - 화면 전체를 덮고 포커스를 가둔다(Radix Dialog). 떠 있는 동안 뒤의 지도·시트는 눌리지 않는다.
 * - 바깥을 눌러도 닫히지 않는다(바깥이 없다). 닫기는 ✕ 와 Esc, 다 본 뒤에는 「보상 받고 닫기」.
 * - seconds 동안 센 뒤에 닫으면 finished = true. 그 전에 닫아도 막지 않는다 — 시간 제한 때문에 갇히지 않게(WCAG 2.2.1).
 * 길이는 부르는 쪽이 응답 값으로 준다(#733). 화면은 숫자를 적지 않는다.
 */
export default function TestAdWindow({ seconds, onClose }: { seconds: number; onClose: (finished: boolean) => void }) {
  // 끝나는 시각은 창이 뜰 때 한 번 정한다. 매초 1씩 빼지 않고 시계로 다시 잰다(타이머가 늦게 돌아도 맞게).
  const [deadline] = useState(() => Date.now() + seconds * 1000)
  const [left, setLeft] = useState(() => Math.max(0, Math.ceil(seconds)))
  const finished = left === 0

  useEffect(() => {
    if (finished) return
    const id = setInterval(() => setLeft(Math.max(0, Math.ceil((deadline - Date.now()) / 1000))), 250)
    return () => clearInterval(id)
  }, [finished, deadline])

  // 앱 트리 밖에서 통째로 빼서 닫으므로 Radix 의 닫힘 복귀가 돌지 않는다(ConfirmDialog 와 같은 이유). 연 버튼으로 직접 돌려준다.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    return () => opener?.focus()
  }, [])

  const close = () => onClose(finished)

  return (
    <Dialog.Root open onOpenChange={(open) => !open && close()}>
      <Dialog.Portal>
        <Dialog.Content
          onPointerDownOutside={(e) => e.preventDefault()}
          onInteractOutside={(e) => e.preventDefault()}
          className="enter-fade fixed inset-0 z-50 flex flex-col bg-[var(--surface-overlay)] outline-none"
        >
          <div className="flex items-center justify-between gap-2 px-4 pt-[max(12px,env(safe-area-inset-top))]">
            <span className="tag tag-neutral">테스트 광고</span>
            <div className="flex items-center gap-1">
              {/* 남은 초는 매초 바뀌어 읽어 주지 않는다. 다 봤다는 것만 아래 status 줄이 알린다. */}
              {!finished && (
                <span aria-hidden="true" className="text-xs text-ink-500">
                  {left}초
                </span>
              )}
              <button type="button" onClick={close} aria-label="광고 닫기" className="inline-flex size-11 items-center justify-center text-ink-600">
                <X size={20} aria-hidden="true" />
              </button>
            </div>
          </div>
          <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center">
            <Dialog.Title className="break-keep text-title font-bold text-ink-900">테스트 광고예요</Dialog.Title>
            <Dialog.Description className="break-keep text-sm text-ink-600">
              끝까지 보면 보상을 받아요
            </Dialog.Description>
            <p role="status" className="break-keep text-xs text-ink-500">
              {finished ? '다 봤어요. 닫으면 보상을 받아요' : '지금 닫으면 보상을 받지 못해요'}
            </p>
          </div>
          <div className="px-4 pb-[max(16px,env(safe-area-inset-bottom))]">
            {finished && (
              <button type="button" onClick={close} className="btn-primary btn-lg w-full">
                보상 받고 닫기
              </button>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
