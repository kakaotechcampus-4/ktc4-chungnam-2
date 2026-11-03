import { CircleHelp, Database, ExternalLink } from 'lucide-react'

import AdviceText from './AdviceText'
import type { AgentFactLineDto, AgentWebCheckDto } from './model'

/**
 * value는 아이콘 모양에만 쓴다. 판정 문구(「데이터가 틀릴 수 있어요」 등)는 서버 문구에 이미 들어 있어 화면이 더하지 않는다.
 * 참·거짓은 좋고 나쁨이 아니라 「특징이 있다·없다」라서 같은 「데이터」 아이콘이고, 모름만 다르다. ✓·✕와 좋음·나쁨 색은 쓰지 않는다 —
 * ✓는 「좋다」, ✕는 「반대가 틀렸다」로 읽혀 우리 데이터가 구성원의 반대를 판정하게 된다(agent-v2 6.6, #1182 검수).
 */
const VALUE_ICON: Record<AgentFactLineDto['value'], typeof Database> = { yes: Database, no: Database, unknown: CircleHelp }

/** 우리 데이터 확인(agent-v2 6.6, 16.2). 그 핀 장소의 라벨로 서버가 렌더한 고정 문구 줄, 많아야 2줄. 없거나 비면 그리지 않는다. */
export default function FactLines({ facts }: { facts: AgentFactLineDto[] | undefined }) {
  if (!facts?.length) return null
  return (
    <section className="space-y-1.5">
      <h3 className="text-sm font-bold text-ink-900">우리 데이터</h3>
      <ul className="space-y-1 text-body text-ink-900">
        {facts.map((f, i) => {
          const Icon = VALUE_ICON[f.value]
          return (
            <li key={i}>
              <div className="flex items-start gap-1.5">
                <Icon size={14} aria-hidden className="mt-0.5 shrink-0 text-ink-500" />
                <span className="min-w-0 break-keep">
                  <AdviceText segments={f.segments} />
                </span>
              </div>
              {f.web && <WebSummary web={f.web} />}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

/**
 * 웹 요약(agent-v2 6.8, #1152 ④). 그 「모름」 줄 바로 아래(아이콘 폭만큼 들여서)에 붙는다.
 * found 문장은 모델이 웹 글을 옮긴 것이고 서버는 출처만 대조했다(2절 3번의 예외) — 그래서 머리에 「확인되지 않음」을 달고,
 * 판정 아이콘·good·bad 색·판정 글을 붙이지 않는다. 문장·notice·출처 이름은 서버 글 그대로다.
 */
function WebSummary({ web }: { web: AgentWebCheckDto }) {
  if (web.status !== 'found') {
    if (!web.notice) return null
    return <p className="mt-1 ml-5 break-keep text-xs text-ink-500">{web.notice}</p>
  }
  if (!web.statements.length) return null
  return (
    <div className="mt-1.5 ml-5 space-y-1.5 rounded-md border border-brand-300 bg-[var(--pingo-bg)] p-2.5">
      <h4 className="flex items-center gap-1.5 text-xs font-semibold text-ink-600">
        <span className="tag tag-ai">AI</span> 웹 요약 · 확인되지 않음
      </h4>
      <ul className="space-y-1.5">
        {web.statements.map((s, i) => (
          <li key={i}>
            <p className="break-keep text-body text-ink-900">{s.text}</p>
            <a
              href={s.source_url}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={`${s.source_name}에서 보기, 새 탭`}
              className="btn-link text-xs"
            >
              {s.source_name} <ExternalLink size={12} aria-hidden="true" />
            </a>
          </li>
        ))}
      </ul>
    </div>
  )
}
