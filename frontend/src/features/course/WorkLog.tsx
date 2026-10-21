import PingoLoading from '@/ui/PingoLoading'

import { BY, understandBody, type CourseStepDto } from './model'

/**
 * 작업 기록 — 누가 무엇을 했는지 한 줄씩. 위에서 아래로 쌓이고, 앞 줄은 바뀌지 않으니(서버 계약) 줄 번호가 키다.
 * 첫 「이해」 줄만 AI 카드("이렇게 이해했어요")로 크게 보인다. 질문 줄도 이번엔 버튼 없이 기록으로만 둔다.
 */
export default function WorkLog({ steps, running }: { steps: CourseStepDto[]; running: boolean }) {
  // AI 가 요청을 읽는 처음 몇 초는 steps 가 비어 있다.
  if (steps.length === 0) return running ? <PingoLoading label="요청을 읽고 있어요" /> : null
  return (
    <ol aria-label="작업 기록" aria-live={running ? 'polite' : undefined} className="space-y-2">
      {steps.map((step, i) => (
        <li key={i}>{i === 0 && step.stage === '이해' ? <UnderstandCard step={step} /> : <StepRow step={step} />}</li>
      ))}
    </ol>
  )
}

function ByChip({ by }: { by: CourseStepDto['by'] }) {
  return <span className={`tag ${BY[by].tag}`}>{BY[by].label}</span>
}

function UnderstandCard({ step }: { step: CourseStepDto }) {
  return (
    <section className="space-y-1.5 rounded-xl border-[1.5px] border-brand-300 bg-brand-50 p-3.5">
      <h3 className="flex items-center gap-1.5 text-sm font-bold text-ink-900">
        <ByChip by={step.by} />
        이렇게 이해했어요
      </h3>
      <p className="break-keep text-body text-ink-900">{understandBody(step.text)}</p>
      {step.by_detail && <p className="text-xs text-ink-500">{step.by_detail}</p>}
    </section>
  )
}

/** 한 줄 = 단계 + 역할 + 누가 칩 + 문장. 섞인 단계의 원문(by_detail)은 보조 글씨로. */
function StepRow({ step }: { step: CourseStepDto }) {
  return (
    <div className="rounded-xl bg-white px-3 py-2.5 ring-1 ring-ink-200">
      <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-ink-600">
        <span className="font-semibold text-ink-900">{step.stage}</span>
        <span aria-hidden="true">·</span>
        <span>{step.role}</span>
        <ByChip by={step.by} />
        {step.by_detail && <span className="text-ink-500">{step.by_detail}</span>}
      </p>
      <p className="mt-1 break-keep text-body text-ink-900">{step.text}</p>
    </div>
  )
}
