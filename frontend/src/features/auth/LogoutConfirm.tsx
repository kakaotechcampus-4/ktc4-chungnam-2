import { useNavigate } from 'react-router'

import ErrorText from '@/ErrorText'
import ConfirmDialog from '@/ui/ConfirmDialog'

import { useLogoutMutation } from './queries'

/** 로그아웃 확인 창(Figma 계정 시트·프로필 시트 공통). 취소는 이전 화면으로 돌아간다. */
export default function LogoutConfirm({ onCancel }: { onCancel: () => void }) {
  const navigate = useNavigate()
  const logout = useLogoutMutation()

  return (
    <ConfirmDialog
      title="로그아웃할까요?"
      body="지도와 핀은 그대로 남아요. 다시 들어오려면 카카오로 로그인하면 돼요."
      ok="로그아웃"
      pending={logout.isPending}
      onCancel={onCancel}
      onOk={() => logout.mutate(undefined, { onSuccess: () => navigate('/', { replace: true }) })}
    >
      {logout.error && <ErrorText message="로그아웃하지 못했어요" error={logout.error} />}
    </ConfirmDialog>
  )
}
