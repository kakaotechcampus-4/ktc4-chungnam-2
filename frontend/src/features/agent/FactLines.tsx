import { CircleHelp, Database } from 'lucide-react'

import AdviceText from './AdviceText'
import type { AgentFactLineDto } from './model'

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
            <li key={i} className="flex items-start gap-1.5">
              <Icon size={14} aria-hidden className="mt-0.5 shrink-0 text-ink-500" />
              <span className="min-w-0 break-keep">
                <AdviceText segments={f.segments} />
              </span>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
