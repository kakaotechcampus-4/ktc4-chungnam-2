import { useState } from 'react'

import ErrorText from '@/ErrorText'
import { showToast } from '@/features/shell/toast'
import ConfirmDialog from '@/ui/ConfirmDialog'
import TextField from '@/ui/TextField'

import { useMeQuery, useUpdateMeMutation } from './queries'

const NAME_MAX = 50

/** 표시 이름 바꾸기(계정 시트·지도 정보 공통). 지도마다 다른 이름은 두지 않는다 — 모든 지도에 같이 바뀐다. */
export default function EditNameDialog({ onCancel }: { onCancel: () => void }) {
  const current = useMeQuery().data?.display_name ?? ''
  const update = useUpdateMeMutation()
  const [name, setName] = useState(current)
  const next = name.trim()

  return (
    <ConfirmDialog
      title="이름 바꾸기"
      body="구성원에게 보이는 이름이에요. 내가 참여한 모든 지도에서 같이 바뀌어요."
      ok="저장"
      pending={update.isPending || next === '' || next === current}
      onCancel={onCancel}
      onOk={() =>
        update.mutate(next, {
          onSuccess: () => {
            showToast('이름을 바꿨어요')
            onCancel()
          },
        })
      }
    >
      <div className="pt-2">
        <TextField value={name} onChange={setName} maxLength={NAME_MAX} label="이름" clearLabel="이름 지우기" />
      </div>
      {update.error && <ErrorText message="이름을 바꾸지 못했어요" error={update.error} />}
    </ConfirmDialog>
  )
}
