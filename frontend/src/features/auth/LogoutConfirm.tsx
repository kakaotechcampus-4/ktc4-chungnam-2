import { useNavigate } from 'react-router'

import ErrorText from '@/ErrorText'

import { useLogoutMutation } from './queries'

/** 로그아웃 확인 창(Figma 계정 시트·프로필 시트 공통). 취소는 이전 화면으로 돌아간다. */
export default function LogoutConfirm({ onCancel }: { onCancel: () => void }) {
  const navigate = useNavigate()
  const logout = useLogoutMutation()

  return (
    <div role="alertdialog" aria-modal="true" aria-label="로그아웃 확인" className="absolute inset-0 flex items-center justify-center bg-black/32 p-6">
      <div className="w-full max-w-sm rounded-2xl bg-white p-5">
        <p className="font-semibold text-ink-900">로그아웃할까요?</p>
        <p className="mt-1 text-sm text-ink-500">지도와 핀은 그대로 남아요. 다시 들어오려면 카카오로 로그인하면 돼요.</p>
        {logout.error && <ErrorText message="로그아웃하지 못했어요" error={logout.error} />}
        <div className="mt-4 grid grid-cols-2 gap-2">
          <button type="button" onClick={onCancel} className="rounded-lg border border-ink-300 py-2.5 text-sm">
            취소
          </button>
          <button
            type="button"
            disabled={logout.isPending}
            onClick={() => logout.mutate(undefined, { onSuccess: () => navigate('/', { replace: true }) })}
            className="rounded-lg bg-brand-600 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
          >
            로그아웃
          </button>
        </div>
      </div>
    </div>
  )
}
