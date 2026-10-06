import { useEffect, useState } from 'react'
import { Outlet, useSearchParams } from 'react-router'

import ErrorText from '@/ErrorText'
import AgainstMark from '@/ui/AgainstMark'
import MapIllustration from '@/ui/MapIllustration'

import { isUnauthorized } from './api'
import KakaoButton from './KakaoButton'
import { loginErrorMessage } from './model'
import { useMeQuery } from './queries'

/** 로그인해야 볼 수 있는 화면들을 감싼다. 비로그인이면 그 자리에 로그인 화면을 띄운다. */
export default function RequireLogin() {
  const { isPending, error } = useMeQuery()

  if (isPending) return <p className="p-4 text-sm text-ink-500">확인하는 중…</p>
  if (isUnauthorized(error)) return <LoginScreen />
  if (error) {
    return (
      <div className="p-4">
        <ErrorText message="로그인 상태를 확인하지 못했어요" error={error} />
      </div>
    )
  }
  return <Outlet />
}

const STEPS = [
  '가고 싶은 곳을 핀으로 찍어요',
  <>♥ 좋음 · △ 조율 필요 · <AgainstMark /> 반대로 의견을 남겨요</>,
  '반대가 있으면 AI가 대안을 찾아줘요',
]

/** 로그인(랜딩) — Figma 1절. 로그인에 실패하고 돌아왔으면(`?login_error=`) 이유를 알리고 주소에서 지운다. */
function LoginScreen() {
  const [params, setParams] = useSearchParams()
  // 주소에서 지우기 전에 문구를 붙잡아 둔다 — 지운 뒤에도 안내는 남고, 새로고침하면 다시 뜨지 않는다.
  const [failure] = useState(() => loginErrorMessage(params.get('login_error')))

  useEffect(() => {
    if (!params.has('login_error')) return
    const next = new URLSearchParams(params)
    next.delete('login_error')
    setParams(next, { replace: true })
  }, [params, setParams])

  return (
    <div className="flex min-h-dvh flex-col bg-white px-5 pb-8 pt-24">
      <h1 className="text-3xl font-extrabold text-brand-600">핀고핀고</h1>
      <p className="mt-1 font-semibold text-ink-900">같이 갈 곳을 한 지도에 모아요</p>
      <MapIllustration className="mt-6" />
      <ol className="mt-6 space-y-3">
        {STEPS.map((step, i) => (
          <li key={i} className="flex items-center gap-3 text-sm text-ink-700">
            <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-brand-50 text-xs font-semibold text-brand-600">
              {i + 1}
            </span>
            {step}
          </li>
        ))}
      </ol>
      <div className="mt-auto space-y-3 text-center">
        {failure && (
          <p role="alert" className="text-sm font-semibold text-warn-text">
            {failure}
          </p>
        )}
        <KakaoButton />
        <p className="text-xs text-ink-500">카카오 표시 이름만 받아요</p>
      </div>
    </div>
  )
}
