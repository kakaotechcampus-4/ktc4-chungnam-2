import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'

import { FEATURES } from '@/features/onboarding/features'
import WelcomeScene from '@/features/onboarding/WelcomeScene'
import { markWelcomeSeen } from '@/features/onboarding/welcomeSeen'
import StepDots from '@/ui/StepDots'

/** 이만큼 넘게 옆으로 밀어야 장이 넘어간다. 그 아래는 누르기로 본다(바텀시트 끌기와 같은 값). */
const SWIPE = 40

/**
 * 첫 로그인 온보딩 — 기능 하나에 한 장. 핑고가 그 기능을 쓰는 장면 + 제목 한 줄 + 쓰는 법 한 줄(FEATURES).
 * 내 지도 목록이 처음 열릴 때 한 번 이리 보낸다(welcomeSeen). 끝내거나 건너뛰면 목록으로 돌아가고,
 * 초대로 들어와 로그인한 사람은 목록이 그 초대로 이어 보낸다.
 * 좁은 화면은 장면 위·글 아래, 768px 이상은 종이 배경 가운데 넓은 카드에 장면 왼쪽·글 오른쪽 두 칸이다.
 */
export default function WelcomePage() {
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
  const startX = useRef<number | null>(null)
  const last = step === FEATURES.length - 1
  const { Icon, text, detail, scene } = FEATURES[step]

  const finish = () => {
    markWelcomeSeen()
    navigate('/', { replace: true })
  }
  const go = (next: number) => setStep(Math.min(Math.max(next, 0), FEATURES.length - 1))

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight') setStep((s) => Math.min(s + 1, FEATURES.length - 1))
      if (e.key === 'ArrowLeft') setStep((s) => Math.max(s - 1, 0))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="min-h-dvh bg-white md:flex md:items-center md:justify-center md:bg-ink-50 md:px-8 md:py-10">
      <main
        // 옆으로 미는 손가락은 이 화면이 받는다(세로 스크롤만 브라우저에 맡긴다).
        onPointerDown={(e) => (startX.current = e.clientX)}
        onPointerUp={(e) => {
          if (startX.current === null) return
          const dx = e.clientX - startX.current
          startX.current = null
          if (dx <= -SWIPE) go(step + 1)
          else if (dx >= SWIPE) go(step - 1)
        }}
        onPointerCancel={() => (startX.current = null)}
        className="mx-auto flex min-h-dvh w-full max-w-[480px] touch-pan-y flex-col px-5 pb-6 pt-2 md:mx-0 md:min-h-0 md:max-w-[960px] md:rounded-2xl md:border md:border-ink-200 md:bg-white md:px-10 md:pb-10 md:pt-4"
      >
        <div className="flex h-11 items-center justify-between">
          {step > 0 ? (
            <button type="button" onClick={() => go(step - 1)} className="btn-text">
              이전
            </button>
          ) : (
            <span />
          )}
          {!last && (
            <button type="button" onClick={finish} className="btn-text">
              건너뛰기
            </button>
          )}
        </div>

        <div className="mt-2 flex flex-1 flex-col md:mt-4 md:grid md:grid-cols-[1.15fr_1fr] md:items-center md:gap-12">
          {/* 장이 바뀌면 장면을 처음 단계부터 다시 돌린다. */}
          {/* 좁은 화면은 남는 높이를 장면 위(빈 칸)와 글 아래에 반씩 나눠 장면·글이 가운데에 온다. */}
          <div className="flex-1 md:hidden" />
          <WelcomeScene key={step} kind={scene} />

          <div className="mt-8 flex flex-1 flex-col md:mt-0">
            {/* 장이 바뀌면 새로 그려 한 번 페이드한다(움직임 줄이기면 끈다). */}
            <section key={step} aria-live="polite" className="enter-fade flex flex-col items-center text-center md:items-start md:text-left">
              <span className="flex size-8 items-center justify-center rounded-md bg-brand-50 text-brand-600">
                <Icon size={16} aria-hidden="true" />
              </span>
              <h1 className="mt-3 text-balance break-keep text-xl font-bold text-ink-900 md:text-2xl">{text}</h1>
              <p className="mt-2 text-balance break-keep text-body text-ink-700">{detail}</p>
            </section>

            <div className="mt-auto pt-8 md:mt-10 md:pt-0">
              <StepDots count={FEATURES.length} current={step} className="justify-center md:justify-start" />
              <button type="button" onClick={last ? finish : () => go(step + 1)} className="btn-primary btn-lg mt-6 w-full md:w-48">
                {last ? '시작하기' : '다음'}
              </button>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
