import ErrorText from '@/ErrorText'
import ConfirmDialog from '@/ui/ConfirmDialog'

import { useWithdrawMutation } from './queries'

/** 회원 탈퇴 확인 창(#155). 되돌릴 수 없다 — 같은 카카오 계정으로 다시 가입해도 이전 지도는 돌아오지 않는다. */
export default function WithdrawConfirm({ onCancel }: { onCancel: () => void }) {
  const withdraw = useWithdrawMutation()

  return (
    <ConfirmDialog
      title="정말 탈퇴할까요?"
      body="내가 남긴 반응과 사유는 삭제되고, 내가 찍은 핀은 ‘탈퇴한 구성원’의 이름으로 남아요."
      note="내가 방장인 지도는 다른 구성원에게 넘어가고, 혼자인 지도는 삭제돼요."
      ok="탈퇴"
      danger
      pending={withdraw.isPending}
      onCancel={onCancel}
      // 계정이 사라졌으니 화면 상태를 통째로 버린다. 지금 주소가 '/'라서 navigate 로는 다시 그려지지 않는다 — 새로 읽는다.
      onOk={() => withdraw.mutate(undefined, { onSuccess: () => window.location.replace('/') })}
    >
      {withdraw.error && <ErrorText message="탈퇴하지 못했어요" error={withdraw.error} />}
    </ConfirmDialog>
  )
}
