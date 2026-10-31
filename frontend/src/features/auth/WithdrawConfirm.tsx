import ErrorText from '@/ErrorText'
import ConfirmDialog from '@/ui/ConfirmDialog'

import { useWithdrawMutation } from './queries'

/**
 * 회원 탈퇴 확인 창(#155). 탈퇴 뒤 7일 안에는 같은 카카오 계정으로 되살릴 수 있다(#855) — 지도 참여와 핀 작성자 표시는 돌아오고
 * 반응·사유는 탈퇴할 때 지워져 돌아오지 않는다. 7일은 이 창에 내려 주는 값이 없어 이슈 문구대로 적었다(#858, 사용자 결정).
 */
export default function WithdrawConfirm({ onCancel }: { onCancel: () => void }) {
  const withdraw = useWithdrawMutation()

  return (
    <ConfirmDialog
      title="정말 탈퇴할까요?"
      body="탈퇴하면 7일 동안은 같은 카카오 계정으로 계정을 되살릴 수 있고, 7일이 지나면 계정 정보가 모두 삭제돼요. 남긴 의견은 탈퇴할 때 바로 지워져요."
      note="내가 찍은 핀은 ‘탈퇴한 구성원’의 이름으로 남아요. 내가 방장인 지도는 다른 구성원에게 넘어가고, 혼자인 지도는 삭제돼요."
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
