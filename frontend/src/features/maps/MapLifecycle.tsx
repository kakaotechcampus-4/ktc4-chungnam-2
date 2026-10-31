import { useState } from 'react'
import { useNavigate } from 'react-router'

import { ApiError } from '@/api'
import ErrorText from '@/ErrorText'
import { showToast } from '@/features/shell/toast'
import ConfirmDialog from '@/ui/ConfirmDialog'
import { josa } from '@/ui/josa'

import { mapChanges, tripReady, type MapHeaderView, type TripDraft } from './model'
import { useDeleteMapMutation, useLeaveMapMutation, useUpdateMapMutation } from './queries'
import TripFields from './TripFields'

/**
 * 지도 제목·날짜·지역 수정 창(방장만, #465·#480). 바뀐 칸만 보낸다. 지역은 바꾸기만 되고 지울 수 없다.
 * 이미 받은 AI 추천 결과는 그대로라는 것을 미리 알린다(api-spec PATCH /maps/{mapId}).
 */
export function EditMapDialog({ map, onCancel }: { map: MapHeaderView; onCancel: () => void }) {
  const update = useUpdateMapMutation(map.id)
  const [draft, setDraft] = useState<TripDraft>({ title: map.title, region: map.region ?? null, startDate: map.startDate, endDate: map.endDate })
  const body = mapChanges(map, draft)

  return (
    <ConfirmDialog
      title="지도 정보 수정"
      body="바꾼 내용은 모든 구성원에게 바로 보여요. 이미 받은 AI 추천은 그대로 남아요."
      ok="저장"
      pending={update.isPending || !body || !tripReady(draft)}
      onCancel={onCancel}
      onOk={() =>
        body &&
        update.mutate(body, {
          onSuccess: () => {
            showToast('지도 정보를 고쳤어요')
            onCancel()
          },
        })
      }
    >
      <div className="pt-2">
        <TripFields value={draft} onChange={setDraft} regionClearable={!map.region} />
      </div>
      {update.error && <ErrorText message="지도 정보를 고치지 못했어요" error={update.error} />}
    </ConfirmDialog>
  )
}

/**
 * 지도 나가기 확인 창(#369). 나가면 내 의견(반응·사유)은 지워지고 내가 찍은 핀은 '나간 구성원'의 핀으로 남는다.
 * 방장이 나가면 먼저 들어온 구성원에게 방장이 넘어간다 — 누구인지는 서버가 정해 준다(`next_owner`).
 */
export function LeaveMapConfirm({ mapId, nextOwnerName, onCancel }: { mapId: string; nextOwnerName?: string; onCancel: () => void }) {
  const navigate = useNavigate()
  const leave = useLeaveMapMutation(mapId)
  const cannotLeave = leave.error instanceof ApiError && leave.error.code === 'OWNER_CANNOT_LEAVE'

  return (
    <ConfirmDialog
      title="이 지도에서 나갈까요?"
      body={`내가 남긴 의견은 지워지고, 내가 찍은 핀은 '나간 구성원'의 핀으로 남아요.${
        nextOwnerName ? ` ${nextOwnerName}${josa(nextOwnerName, '이', '가')} 새 방장이 돼요.` : ''
      }`}
      ok="나가기"
      danger
      pending={leave.isPending}
      onCancel={onCancel}
      onOk={() =>
        leave.mutate(undefined, {
          onSuccess: () => {
            showToast('지도에서 나왔어요')
            navigate('/', { replace: true })
          },
        })
      }
    >
      {cannotLeave ? (
        <p className="text-sm font-semibold text-warn-text">혼자 남은 방장은 나갈 수 없어요. 나가는 대신 지도를 삭제해 주세요.</p>
      ) : (
        leave.error && <ErrorText message="지도에서 나가지 못했어요" error={leave.error} />
      )}
    </ConfirmDialog>
  )
}

/** 지도 삭제 확인 창(방장만, #369). 모든 구성원에게서 사라진다. */
export function DeleteMapConfirm({ mapId, title, onCancel }: { mapId: string; title: string; onCancel: () => void }) {
  const navigate = useNavigate()
  const del = useDeleteMapMutation(mapId)

  return (
    <ConfirmDialog
      title="지도를 삭제할까요?"
      body={`‘${title}’의 핀과 의견이 모든 구성원에게서 사라져요. 되돌릴 수 없어요.`}
      ok="삭제"
      danger
      pending={del.isPending}
      onCancel={onCancel}
      onOk={() =>
        del.mutate(undefined, {
          onSuccess: () => {
            showToast('지도를 삭제했어요')
            navigate('/', { replace: true })
          },
        })
      }
    >
      {del.error && <ErrorText message="지도를 삭제하지 못했어요" error={del.error} />}
    </ConfirmDialog>
  )
}
