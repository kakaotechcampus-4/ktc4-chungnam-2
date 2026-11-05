import { useState } from 'react'

import { useSheetStore } from '@/features/shell/sheetStore'
import MapPingo from '@/ui/MapPingo'

import AgentSheet from './AgentSheet'
import { useAgentQuery } from './queries'

/** 말풍선을 두 번 열어 보면 이 기기에선 숨긴다(#1433) — 지도를 가린다. 화면 편의라 브라우저 저장소에 센다. */
const OPENS_KEY = 'pingo-advice-opens'
const BUBBLE_OPENS = 2

function readOpens() {
  try {
    return Number(localStorage.getItem(OPENS_KEY)) || 0
  } catch {
    return 0
  }
}

/**
 * 「핑고 AI 조언」 버튼(agent-v2 16.1). 조언은 지도 단위라 지도가 떠 있는 네 탭 모두의 지도 왼쪽 아래에 있다(#1162) —
 * 오른쪽 지도 버튼 묶음과 같은 높이로 시트 윗변을 따라 오르내린다. 안내자 핑고가 손을 흔들며 말을 거는 모양(말풍선)이다.
 * 새 제안을 아직 안 봤으면 말풍선에 귤색 점(새 소식, #1223). 모드가 꺼져 있어도 버튼은 보이고 점만 숨긴다. 요약 갱신에는 점을 켜지 않는다.
 * 핑고는 3D 지도 핑고이고(#1433), 지도를 끄는 동안 말풍선만 흐려지고 핑고는 끈 방향을 보며 걷는다.
 * 말풍선을 숨긴 뒤에는 핑고만 남아 누르는 자리가 되고, 새 제안 점은 핑고 머리 옆에 붙는다.
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
  /** 지도를 끄는 동안 말풍선이 지도 버튼과 같이 흐려진다. 핑고는 남아서 걷는다. */
  fading: boolean
  /** 넓은 화면 — 지도 영역 왼쪽 아래 고정. */
  docked?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [opens, setOpens] = useState(readOpens)
  const heading = useSheetStore((s) => s.mapHeading)
  const state = useAgentQuery(mapId).data
  const dot = Boolean(state?.settings.enabled && state.has_unseen)
  const bubble = opens < BUBBLE_OPENS
  const dotClass = 'absolute size-3 rounded-full bg-[var(--notify-dot)] ring-2 ring-white'

  function onOpen() {
    setOpen(true)
    if (!bubble) return
    setOpens(opens + 1)
    try {
      localStorage.setItem(OPENS_KEY, String(opens + 1))
    } catch {
      // 저장소를 못 쓰면(사생활 보호 창 등) 다음에 다시 센다.
    }
  }

  return (
    <>
      <button
        type="button"
        hidden={hidden}
        onClick={onOpen}
        aria-label={dot ? '핑고 AI 조언, 새 제안 있음' : '핑고 AI 조언'}
        className={`absolute left-4 ${docked ? 'pointer-events-auto bottom-4' : 'bottom-[calc(100%+12px)]'} press flex min-h-11 min-w-11 items-center gap-2`}
      >
        {/* 지도 위에 맨몸으로 서서 그림자로 띄운다. 휴대폰 48 · 태블릿 56 · PC 64. */}
        <span className="relative block drop-shadow-md">
          <MapPingo heading={heading} wave={bubble} className="size-12 md:size-14 lg:size-16" />
          {/* 3D 그림은 둘레가 비어 있어 모서리가 아니라 모자 오른쪽에 붙인다. */}
          {!bubble && dot && <span aria-hidden="true" className={`${dotClass} right-[12%] top-[16%]`} />}
        </span>
        {bubble && (
          <span
            className={`relative flex h-9 items-center rounded-xl bg-white px-3 text-sm font-bold text-brand-600 shadow-float transition-opacity ${
              fading ? 'opacity-0 duration-150' : 'opacity-100 delay-800 duration-300'
            }`}
          >
            {/* 말풍선 꼬리 — 핑고 쪽을 가리킨다. */}
            <span aria-hidden="true" className="absolute -left-1 top-1/2 size-2.5 -translate-y-1/2 rotate-45 bg-white" />
            핑고 AI 조언
            {dot && <span aria-hidden="true" className={`${dotClass} -right-1 -top-1`} />}
          </span>
        )}
      </button>
      {open && <AgentSheet mapId={mapId} onClose={() => setOpen(false)} />}
    </>
  )
}
