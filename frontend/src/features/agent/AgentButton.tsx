import { useState } from 'react'

import Pingo from '@/ui/Pingo'

import AgentSheet from './AgentSheet'
import { useAgentQuery } from './queries'

/** 핑고와 말풍선을 합쳐 버튼 하나라서, 어디를 올리거나 눌러도 말풍선(면)이 press 와 같은 잉크로 덮인다. */
const BUBBLE_PRESS =
  'bg-white [@media(hover:hover)]:group-hover:bg-[image:linear-gradient(var(--press-hover),var(--press-hover))] group-active:bg-[image:linear-gradient(var(--press-active),var(--press-active))]'

/**
 * 「핑고 AI 조언」 버튼(agent-v2 16.1). 모든 탭의 지도 왼쪽 아래 — 오른쪽 지도 버튼 묶음과 같은 높이로 시트 윗변을 따라 오르내린다.
 * 안내자 핑고가 손을 흔들며 서 있고, 옆 말풍선이 「핑고 AI 조언」이다(DESIGN.md 「핑고 AI 조언」).
 * 새 제안을 아직 안 봤으면 말풍선에 파란 점(할 일은 파랑). 모드가 꺼져 있어도 버튼은 보이고 점만 숨긴다. 요약 갱신에는 점을 켜지 않는다.
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
        className={`group absolute left-2 ${docked ? 'bottom-4' : 'bottom-[calc(100%+12px)]'} flex h-11 cursor-pointer items-end rounded-xl transition-opacity ${
          fading ? 'pointer-events-none opacity-0 duration-150' : `${docked ? 'pointer-events-auto ' : ''}opacity-100 delay-800 duration-300`
        }`}
      >
        {/* 지도 위에 바로 서 있어서 어떤 바탕에서도 보이게 그림자를 깐다. 머리 핀이 말풍선 위로 솟는다.
            wave 는 오른손을 드는데 그쪽이 말풍선이라, 좌우로 뒤집어 바깥 손을 흔들게 한다. */}
        <span className="-mb-0.5 -scale-x-100 drop-shadow-[0_2px_3px_rgba(20,22,31,0.2)]">
          <Pingo mood="wave" size={52} />
        </span>
        <span className={`relative ml-1 flex h-11 items-center rounded-xl px-3 text-sm font-bold text-brand-600 shadow-float ${BUBBLE_PRESS}`}>
          {/* 말풍선 꼬리 — 핑고 쪽을 가리킨다. */}
          <span aria-hidden="true" className={`absolute -left-1 bottom-3.5 size-2.5 rotate-45 rounded-[2px] ${BUBBLE_PRESS}`} />
          <span className="relative">핑고 AI 조언</span>
          {dot && <span aria-hidden="true" className="absolute -right-1 -top-1 size-3 rounded-full bg-[var(--notify-dot)] ring-2 ring-white" />}
        </span>
      </button>
      {open && <AgentSheet mapId={mapId} onClose={() => setOpen(false)} />}
    </>
  )
}
