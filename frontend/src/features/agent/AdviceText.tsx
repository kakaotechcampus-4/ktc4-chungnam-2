import type { AgentAdviceLineDto } from './model'

/**
 * 서버가 렌더한 문장 한 줄을 조각대로 잇는다(#717). 슬롯이나 숫자를 만들지 않는다.
 * quote 는 구성원 의견이라 따옴표 + 회색 면으로 에이전트 말과 구분하고, 누가 썼는지는 붙이지 않는다(agent-v2 2절 11번). pin 은 핀 이름 모양.
 */
export default function AdviceText({ line }: { line: AgentAdviceLineDto }) {
  return (
    <>
      {line.segments.map((s, i) =>
        s.kind === 'quote' ? (
          <q key={i} className="rounded-sm bg-ink-100 px-1 text-ink-700">
            {s.text}
          </q>
        ) : s.kind === 'pin' ? (
          <strong key={i} className="font-semibold text-ink-900">
            {s.text}
          </strong>
        ) : (
          <span key={i}>{s.text}</span>
        ),
      )}
    </>
  )
}
