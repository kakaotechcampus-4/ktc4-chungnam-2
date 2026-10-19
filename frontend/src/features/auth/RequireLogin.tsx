import { useEffect, useState } from 'react'
import { Link, Outlet, useSearchParams } from 'react-router'

import { ChevronRight, CircleCheck, UserRound } from 'lucide-react'

import ErrorText from '@/ErrorText'
import ModalSheet from '@/features/shell/ModalSheet'
import AgainstMark from '@/ui/AgainstMark'
import MapIllustration from '@/ui/MapIllustration'
import Pingo from '@/ui/Pingo'
import PingoLoading from '@/ui/PingoLoading'
import SheetTitle from '@/ui/SheetTitle'
import Wordmark from '@/ui/Wordmark'

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

const FEATURES = [
  '가고 싶은 곳을 핀으로 찍어요',
  <>♥ 좋음 · <AgainstMark /> 반대로 의견을 남겨요</>,
  '반대가 있으면 AI가 대안을 찾아줘요',
  '정한 곳은 확정 리스트에 모아요',
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
 * 로그인(랜딩) — 위에서부터 이름 → 날아가는 핑고 → 시작 버튼 둘 → 할 수 있는 일 → 약관 동의 줄.
 * 넓은 화면(768px 이상)은 종이 배경 가운데 입구 카드다(#602).
 */
function LoginScreen() {
  const loginError = useLoginError()
  const [sheet, setSheet] = useState<'guest' | 'terms' | null>(null)
  const close = () => setSheet(null)
  return (
    <div className="min-h-dvh bg-white md:flex md:items-center md:justify-center md:bg-ink-50 md:px-5 md:py-10">
      <main className="mx-auto flex min-h-dvh w-full max-w-[480px] flex-col px-5 pb-6 pt-14 md:mx-0 md:min-h-0 md:max-w-[400px] md:rounded-2xl md:border md:border-ink-200 md:bg-white md:px-8 md:py-10">
        <h1>
          <Wordmark className="h-10 w-auto" />
        </h1>
        <p className="mt-1 font-semibold text-ink-900">같이 갈 곳을 한 지도에 모아요</p>
        <LoginHero />

        <p className="mt-6 text-balance break-keep text-center text-sm text-ink-500">3초면 시작! 카카오에서 이름을 받아서 활용해요</p>
        {/* 빨강은 핀·🚫·되돌릴 수 없는 동작 전용이라(영역 분리 규칙) 로그인 실패는 주의색이다. */}
        {loginError && (
          <p role="alert" className="mt-3 rounded-xl border border-[var(--warn-line)] bg-[var(--warn-bg)] px-3 py-2.5 text-center text-sm font-semibold text-[var(--warn-text)]">
            {loginError}
          </p>
        )}
        {/* 카카오가 주 입구라 큰 버튼, 게스트는 한 단계 작은 버튼이다. */}
        <div className="mt-3 space-y-2">
          <KakaoButton retry={Boolean(loginError)} />
          <button type="button" onClick={() => setSheet('guest')} className="btn-neutral btn-md w-full">
            <UserRound size={16} aria-hidden="true" /> 게스트로 시작하기
            {/* 360px 아래에선 버튼 글자가 두 줄로 깨져서 덧말을 뺀다. */}
            <span className="font-normal text-ink-500 max-[359px]:hidden">
              · <span className="underline underline-offset-2">이름 입력</span>
            </span>
          </button>
        </div>

        <section className="mt-8 border-t border-ink-200 pt-6">
          <h2 className="text-center text-sm font-bold text-ink-900">핑고핑고에서 누릴 수 있는 기능이에요</h2>
          <ul className="mt-4 space-y-3">
            {FEATURES.map((feature, i) => (
              <li key={i} className="flex items-center gap-3 text-sm text-ink-700">
                <CircleCheck size={16} className="shrink-0 text-brand-600" aria-hidden="true" />
                <span className="break-keep">{feature}</span>
              </li>
            ))}
          </ul>
        </section>

        {/* 법적 고지라 이 줄만 「~됩니다」체다. 한 줄에 다 넣으면 393px에서 끝말만 떨어져서 줄을 직접 나눈다. */}
        <p className="mt-auto pt-8 text-center text-xs leading-relaxed text-ink-500 md:mt-8 md:pt-0">
          카카오나 게스트로 시작하면
          <br />
          <button type="button" onClick={() => setSheet('terms')} className="font-semibold text-brand-600 underline underline-offset-2">
            이용약관
          </button>
          에 동의하는 것으로 간주됩니다
        </p>
      </main>

      {sheet === 'guest' && <GuestSheet onClose={close} />}
      {sheet === 'terms' && <TermsSheet onClose={close} />}
    </div>
  )
}

/** 지도 그림 위로 망토 두른 핑고가 날아간다. 장식이라 그림 둘 다 스크린 리더에서 숨는다. */
function LoginHero() {
  return (
    <div className="relative mt-16">
      <MapIllustration />
      {/* 지도에 떨어진 그림자 — 핑고가 지도 위에 떠 있다는 걸 보여 준다. */}
      <div className="absolute left-[44%] top-[44%] h-2.5 w-20 rounded-full bg-ink-300/60 blur-[2px]" />
      <div className="absolute left-[34%] top-[-30%]">
        <Pingo mood="fly" size={88} />
      </div>
    </div>
  )
}

/**
 * 게스트 참여(v2, #472·#485)는 초대 링크로만 들어간다 — 서버가 초대 토큰 없이는 게스트를 만들지 않는다.
 * 그래서 입구에서는 방법만 알려 주고, 이름 입력은 초대 화면이 받는다(#485).
 */
function GuestSheet({ onClose }: { onClose: () => void }) {
  return (
    <ModalSheet label="게스트로 시작하기" onClose={onClose}>
      <div className="flex items-center gap-3">
        <Pingo mood="wave" size={44} />
        <SheetTitle>게스트로 시작하기</SheetTitle>
      </div>
      <p className="mt-3 break-keep text-sm text-ink-700">
        친구에게 받은 초대 링크를 열고 이름만 입력하면 바로 그 지도에 참여해요.
      </p>
      <ul className="mt-4 space-y-2 rounded-xl bg-ink-50 p-4 text-sm text-ink-700">
        <li className="flex gap-2"><CircleCheck size={16} className="mt-0.5 shrink-0 text-brand-600" aria-hidden="true" />핀 찍기·의견·AI 추천은 똑같이 쓸 수 있어요</li>
        <li className="flex gap-2"><CircleCheck size={16} className="mt-0.5 shrink-0 text-brand-600" aria-hidden="true" />새 지도를 만들려면 카카오로 로그인해야 해요</li>
        <li className="flex gap-2"><CircleCheck size={16} className="mt-0.5 shrink-0 text-brand-600" aria-hidden="true" />90일 동안 쓰지 않으면 기록이 정리돼요</li>
      </ul>
      <button type="button" onClick={onClose} className="btn-neutral btn-lg mt-5 w-full">
        닫기
      </button>
    </ModalSheet>
  )
}

const TERMS = [
  { to: '/terms', title: '핑고핑고 이용약관' },
  { to: '/privacy', title: '핑고핑고 개인정보처리방침' },
  // 「내 위치」 버튼이 기기 위치를 쓴다(서버로 보내지는 않음).
  { to: '/location-terms', title: '핑고핑고 위치기반서비스 이용약관' },
]

/** 약관 동의 줄의 「이용약관」이 여는 목록. 문서 하나하나는 따로 연다(#602). */
function TermsSheet({ onClose }: { onClose: () => void }) {
  return (
    <ModalSheet label="이용약관 목록" onClose={onClose}>
      <SheetTitle>이용약관 목록</SheetTitle>
      <ul className="mt-4 divide-y divide-ink-200 rounded-xl border border-ink-200">
        {TERMS.map((term) => (
          <li key={term.to}>
            <Link to={term.to} className="flex min-h-14 items-center justify-between gap-3 px-4 py-3">
              <span>
                <span className="block font-semibold text-ink-900">{term.title}</span>
                <span className="text-xs text-ink-500">(필수)</span>
              </span>
              <ChevronRight size={20} className="text-ink-500" aria-hidden="true" />
            </Link>
          </li>
        ))}
      </ul>
      <button type="button" onClick={onClose} className="btn-neutral btn-lg mt-5 w-full">
        닫기
      </button>
    </ModalSheet>
  )
}
