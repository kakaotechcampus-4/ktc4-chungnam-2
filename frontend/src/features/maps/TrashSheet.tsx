import { useState } from 'react'

import ErrorText from '@/ErrorText'
import ModalSheet from '@/features/shell/ModalSheet'
import { showToast } from '@/features/shell/toast'
import { josa } from '@/ui/josa'
import SheetTitle from '@/ui/SheetTitle'

import { restoreMapErrorMessage, type TrashView } from './model'
import { useRestoreMapMutation } from './queries'

/**
 * 삭제한 지도 휴지통(#479). 내가 방장인 지도만, 되살릴 수 있는 기간 안의 것만 서버가 내려 준다.
 * 되살리면 구성원·핀·의견·확정 리스트가 삭제 때 그대로 돌아온다(api-spec POST /maps/{mapId}/restore).
 */
export default function TrashSheet({ trash, onClose }: { trash: TrashView; onClose: () => void }) {
  const restore = useRestoreMapMutation()
  const [failedId, setFailedId] = useState<string | null>(null)

  function revive(id: string, title: string) {
    setFailedId(null)
    restore.mutate(id, {
      onSuccess: () => showToast(`${title}${josa(title, '을', '를')} 되살렸어요`),
      onError: () => setFailedId(id),
    })
  }

  return (
    <ModalSheet label="휴지통" onClose={onClose}>
      <SheetTitle>휴지통</SheetTitle>
      <p className="mb-4 mt-1 text-sm text-ink-500">
        삭제한 지 {trash.retentionDays}일 안이면 되살릴 수 있어요. 되살리면 구성원과 핀, 의견이 그대로 돌아와요
      </p>
      {trash.items.length === 0 && <p className="text-sm text-ink-500">되살릴 지도가 없어요</p>}
      <ul className="space-y-2">
        {trash.items.map((m) => (
          <li key={m.id} className="rounded-xl bg-ink-50 px-3 py-2.5">
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate text-body font-bold text-ink-900">{m.title}</p>
                <p className="text-xs text-ink-500">
                  {m.dates} · {m.daysLeft}일 안에 되살릴 수 있어요
                </p>
              </div>
              <button
                type="button"
                onClick={() => revive(m.id, m.title)}
                disabled={restore.isPending && restore.variables === m.id}
                className="btn-outline btn-sm shrink-0"
              >
                되살리기
              </button>
            </div>
            {failedId === m.id && restore.error && <ErrorText message={restoreMapErrorMessage(restore.error)} error={restore.error} />}
          </li>
        ))}
      </ul>
    </ModalSheet>
  )
}
