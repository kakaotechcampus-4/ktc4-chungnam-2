import { useState } from 'react'

import ErrorText from '@/ErrorText'
import ModalSheet from '@/features/shell/ModalSheet'
import { showToast } from '@/features/shell/toast'
import CardSkeleton from '@/ui/CardSkeleton'
import { josa } from '@/ui/josa'
import SheetTitle from '@/ui/SheetTitle'

import { restorePinErrorMessage } from './model'
import { usePinTrashQuery, useRestorePinMutation } from './queries'

/**
 * 삭제한 핀(#864, #1012). 지도 정보의 「삭제한 핀」에서 연다. 내가 되살릴 수 있는 핀만 서버가 내려 준다(내가 찍은 핀, 방장은 전부) —
 * 화면은 권한을 다시 따지지 않는다. 되살리면 의견이 그대로 돌아오고, 확정이었던 핀은 확정 리스트에도 다시 올라간다.
 * 모양은 지도 휴지통(`features/maps/TrashSheet`)과 같다.
 */
export default function PinTrashSheet({ mapId, onClose }: { mapId: string; onClose: () => void }) {
  const trash = usePinTrashQuery(mapId)
  const restore = useRestorePinMutation(mapId)
  const [failedId, setFailedId] = useState<string | null>(null)

  function revive(id: string, name: string, wasConfirmed: boolean) {
    setFailedId(null)
    restore.mutate(id, {
      onSuccess: () => showToast(`${name}${josa(name, '을', '를')} 되돌렸어요${wasConfirmed ? '. 확정 리스트에도 다시 올렸어요' : ''}`),
      onError: () => setFailedId(id),
    })
  }

  const days = trash.data?.retention_days
  return (
    <ModalSheet label="삭제한 핀" onClose={onClose}>
      <SheetTitle>삭제한 핀</SheetTitle>
      <p className="mb-4 mt-1 text-sm text-ink-500">
        {days ? `삭제한 지 ${days}일 안에는 되돌릴 수 있어요. ` : ''}되돌리면 남긴 의견도 그대로 돌아와요
      </p>
      {trash.isPending && <CardSkeleton />}
      {trash.error && <ErrorText message="삭제한 핀을 불러오지 못했어요" error={trash.error} />}
      {trash.data?.items.length === 0 && <p className="text-sm text-ink-500">되돌릴 핀이 없어요</p>}
      <ul className="space-y-2">
        {trash.data?.items.map(({ pin, days_left, deleted_by_name, was_confirmed }) => {
          const name = pin.place_name ?? '이름 없는 핀'
          return (
            <li key={pin.id} className="rounded-xl bg-ink-50 px-3 py-2.5">
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-body font-bold text-ink-900">{name}</p>
                  <p className="text-xs text-ink-500">
                    {[pin.category, deleted_by_name && `${deleted_by_name}님이 삭제`, `${days_left}일 안에 되돌릴 수 있어요`].filter(Boolean).join(' · ')}
                  </p>
                  {was_confirmed && <p className="text-xs text-ink-500">되돌리면 확정 리스트에도 다시 올라가요</p>}
                </div>
                <button
                  type="button"
                  onClick={() => revive(pin.id, name, was_confirmed)}
                  disabled={restore.isPending && restore.variables === pin.id}
                  className="btn-outline btn-sm shrink-0"
                >
                  되돌리기
                </button>
              </div>
              {failedId === pin.id && restore.error && <ErrorText message={restorePinErrorMessage(restore.error)} error={restore.error} />}
            </li>
          )
        })}
      </ul>
    </ModalSheet>
  )
}
