import { useEffect, useState } from 'react'
import { Link, Outlet, useSearchParams } from 'react-router'

import ErrorText from '@/ErrorText'
import AgainstMark from '@/ui/AgainstMark'
import MapIllustration from '@/ui/MapIllustration'
import PingoLoading from '@/ui/PingoLoading'

import { isUnauthorized } from './api'
import KakaoButton from './KakaoButton'
import { useMeQuery } from './queries'

/** 로그인해야 볼 수 있는 화면들을 감싼다. 비로그인이면 그 자리에 로그인 화면을 띄운다. */
export default function RequireLogin() {
  const { isPending, error } = useMeQuery()

  if (isPending) return <PingoLoading label="로그인 상태를 확인하는 중…" className="min-h-dvh justify-center" />
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
  <>♥ 좋음 · <AgainstMark /> 반대로 의견을 남겨요</>,
  '반대가 있으면 AI가 대안을 찾아줘요',
]

/**
 * 카카오 로그인이 실패하면 서버가 진입점에 `?login_error=`를 붙여 돌려보낸다(#315).
 * 처음 한 번 읽고 주소에서는 지운다 — 새로고침해도 같은 안내가 다시 뜨지 않게.
 */
function useLoginError(): string | null {
  const [params, setParams] = useSearchParams()
  const [code] = useState(() => params.get('login_error'))
  useEffect(() => {
    if (!params.has('login_error')) return
    const next = new URLSearchParams(params)
    next.delete('login_error')
    setParams(next, { replace: true })
  }, [params, setParams])
  if (!code) return null
  return code === 'cancelled' ? '로그인을 취소했어요' : '로그인하지 못했어요. 다시 시도해 주세요'
}

/**
 * 로그인(랜딩) — Figma 1절. 휴대폰은 카카오 버튼을 엄지가 닿는 화면 아래에 둔다.
 * 넓은 화면(768px 이상)은 종이 배경 가운데 입구 카드이고, 버튼이 일러스트 바로 아래로 올라온다(#602).
 */
function LoginScreen() {
  const loginError = useLoginError()
  return (
    <div className="min-h-dvh bg-white md:flex md:items-center md:justify-center md:bg-ink-50 md:px-5 md:py-10">
      <main className="mx-auto flex min-h-dvh w-full max-w-[480px] flex-col px-5 pb-8 pt-24 md:mx-0 md:min-h-0 md:max-w-[400px] md:rounded-2xl md:border md:border-ink-200 md:bg-white md:px-8 md:py-10">
        <h1 className="text-3xl font-extrabold text-brand-600">핑고핑고</h1>
        <p className="mt-1 font-semibold text-ink-900">같이 갈 곳을 한 지도에 모아요</p>
        <MapIllustration className="mt-6" />
        {/* 넓은 화면은 쓰는 법이 버튼 아래 구분선 뒤로 간다. */}
        <ol className="mt-6 space-y-3 md:order-last md:border-t md:border-ink-200 md:pt-6">
          {STEPS.map((step, i) => (
            <li key={i} className="flex items-center gap-3 text-sm text-ink-700">
              <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-brand-50 text-xs font-semibold text-brand-600">
                {i + 1}
              </span>
              <span className="break-keep">{step}</span>
            </li>
          ))}
        </ol>
        <div className="mt-auto space-y-3 pt-6 text-center md:mt-6 md:pt-0">
          {/* 빨강은 핀·🚫·되돌릴 수 없는 동작 전용이라(영역 분리 규칙) 로그인 실패는 주의색이다. */}
          {loginError && (
            <p role="alert" className="rounded-xl border border-[var(--warn-line)] bg-[var(--warn-bg)] px-3 py-2.5 text-sm font-semibold text-[var(--warn-text)]">
              {loginError}
            </p>
          )}
          <KakaoButton retry={Boolean(loginError)} />
          <div className="space-y-1 text-xs leading-relaxed text-ink-500">
            <p>카카오 표시 이름만 받아요</p>
            {/* 한 줄에 다 넣으면 393px에서 끝말만 따로 떨어져서 줄을 직접 나눈다. 법적 고지라 이 줄만 「~됩니다」체다. */}
            <p>
              로그인하면 <LegalLink to="/terms">이용약관</LegalLink>과 <LegalLink to="/privacy">개인정보처리방침</LegalLink>에
              <br />
              동의하는 것으로 간주됩니다
            </p>
          </div>
        </div>
      </main>
    </div>
  )
}

function LegalLink({ to, children }: { to: string; children: string }) {
  return (
    <Link to={to} className="font-semibold text-brand-600 underline underline-offset-2">
      {children}
    </Link>
  )
}
