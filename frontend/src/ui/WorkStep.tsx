import type { components } from '@pingo/contracts/src/types/api'
import { User } from 'lucide-react'

/** 작업 기록 한 줄. AI 코스(`CourseRun.steps`)와 「핑고 AI 조언」(`AgentSuggestion.steps`, #1297)이 같은 모양을 쓴다. */
export type WorkStepDto = components['schemas']['WorkStep']

/** 작업 기록의 「누가」 칩 — 색(tag-*)과 글자를 함께 쓴다. AI 파랑 · 코드 회색 · 사람 회색+사람 아이콘(주의 색은 조건 체크용이라 쓰지 않는다). */
const BY: Record<WorkStepDto['by'], { label: string; tag: string }> = {
  ai: { label: 'AI', tag: 'tag-ai' },
  code: { label: '코드', tag: 'tag-neutral' },
  human: { label: '사람', tag: 'tag-neutral' },
}

export function ByChip({ by }: { by: WorkStepDto['by'] }) {
  return (
    <span className={`tag ${BY[by].tag}`}>
      {by === 'human' && <User size={12} aria-hidden="true" />}
      {BY[by].label}
    </span>
  )
}

/** 한 줄 = 단계 + 역할 + 누가 칩 + 문장. 섞인 단계의 원문(by_detail)은 보조 글씨로. 모르는 단계 이름도 글자 그대로 그린다(#1243). */
export function StepRow({ step }: { step: WorkStepDto }) {
  return (
    <div className="rounded-xl bg-surface px-3 py-2.5 ring-1 ring-ink-200">
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
