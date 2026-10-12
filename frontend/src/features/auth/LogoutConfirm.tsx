import ErrorText from '@/ErrorText'
import ConfirmDialog from '@/ui/ConfirmDialog'

import { useLogoutMutation } from './queries'

/** 로그아웃 확인 창(Figma 계정 시트·프로필 시트 공통). 취소는 이전 화면으로 돌아간다. */
export default function LogoutConfirm({ onCancel }: { onCancel: () => void }) {
  const logout = useLogoutMutation()

  return (
    <ConfirmDialog
      title="로그아웃할까요?"
      body="지도와 핀은 그대로 남아요. 다시 들어오려면 카카오로 로그인하면 돼요."
      ok="로그아웃"
      pending={logout.isPending}
      onCancel={onCancel}
      // 캐시를 비웠는데 지금 주소가 '/'(내 지도 목록)이면 navigate 로는 다시 그려지지 않아 로그인한 채 화면이 남는다 — 새로 읽는다.
      onOk={() => logout.mutate(undefined, { onSuccess: () => window.location.replace('/') })}
    >
      {logout.error && <ErrorText message="로그아웃하지 못했어요" error={logout.error} />}
    </ConfirmDialog>
  )
}
