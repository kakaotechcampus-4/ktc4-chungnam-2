import { useState } from 'react'

import { PingoMark } from '@/ui/Pingo'

import AgentSheet from './AgentSheet'
import { useAgentQuery } from './queries'

/**
 * 「핑고 AI 조언」 버튼(agent-v2 16.1). 마킹 탭 지도 왼쪽 아래 — 오른쪽 지도 버튼 묶음과 같은 높이로 시트 윗변을 따라 오르내린다.
 * 새 제안을 아직 안 봤으면 파란 점(할 일은 파랑). 모드가 꺼져 있어도 버튼은 보이고 점만 숨긴다. 요약 갱신에는 점을 켜지 않는다.
 */
export default function AgentButton({
  mapId,
  hidden,
  fading,
  docked = false,
}: {
  mapId: string
  /** 지도 버튼과 같은 조건(3단계·모달·좁은 화면)에서 숨긴다. */
  hidden: boolean
  /** 지도를 끄는 동안 지도 버튼과 같이 흐려진다. */
  fading: boolean
  /** 넓은 화면 — 지도 영역 왼쪽 아래 고정. */
  docked?: boolean
}) {
  const [open, setOpen] = useState(false)
  const state = useAgentQuery(mapId).data
  const dot = Boolean(state?.settings.enabled && state.has_unseen)

  return (
    <>
      <button
        type="button"
        hidden={hidden}
        tabIndex={fading ? -1 : 0}
        onClick={() => setOpen(true)}
        aria-label={dot ? '핑고 AI 조언 · 새 제안 있음' : '핑고 AI 조언'}
        className={`absolute left-4 ${docked ? 'bottom-4' : 'bottom-[calc(100%+12px)]'} flex h-11 items-center gap-1.5 rounded-xl bg-white pl-2 pr-3 text-sm font-bold text-brand-600 shadow-float transition-opacity ${
          fading ? 'pointer-events-none opacity-0 duration-150' : `${docked ? 'pointer-events-auto ' : ''}opacity-100 delay-800 duration-300`
        }`}
      >
        <PingoMark size={24} />
        핑고 AI 조언
        {dot && <span aria-hidden="true" className="absolute -right-1 -top-1 size-3 rounded-full bg-brand-600 ring-2 ring-white" />}
      </button>
      {open && <AgentSheet mapId={mapId} onClose={() => setOpen(false)} />}
    </>
  )
}
