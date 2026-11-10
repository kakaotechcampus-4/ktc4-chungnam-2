import { useState } from 'react'

import { useSheetStore } from '@/features/shell/sheetStore'
import MapPingo from '@/ui/MapPingo'

import AgentSheet from './AgentSheet'
import { useAgentQuery } from './queries'
import { useIdleStage } from './useIdleStage'

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
 * 아직 안 본 새 제안이 있으면 같은 말풍선이 그 제안의 제목을 말한다(열어 본 횟수와 상관없이). 제목은 서버 고정 문구와 숫자뿐이라 사용자 글이 섞이지 않는다. 모드가 꺼져 있어도 버튼은 보이고 제안 문장만 숨긴다. 요약 갱신에는 문장을 띄우지 않는다.
 * 핑고는 3D 지도 핑고이고(#1433), 지도를 끄는 동안 말풍선만 흐려지고 핑고는 끈 방향을 보며 걷는다.
 * 말풍선이 없으면 핑고만 남아 누르는 자리가 된다.
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
  // 5분 동안 아무것도 안 하면 핑고가 졸다가 이불 덮고 잔다. 손을 대면 바로 깬다.
  const idle = useIdleStage()
  // 조회가 실패하면 제안 문장만 못 띄운다 — 버튼은 남고 시트가 열리면 거기서 오류를 보인다(AgentSheet).
  const state = useAgentQuery(mapId).data
  const speech = state?.settings.enabled && state.has_unseen ? state.active_suggestion?.title : undefined
  const bubble = opens < BUBBLE_OPENS
  const text = speech ?? (bubble ? '핑고 AI 조언' : null)

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
        aria-label={speech ? `핑고 AI 조언, 새 제안: ${speech}` : '핑고 AI 조언'}
        // 넓은 화면은 지도 왼쪽 아래 — 카카오 로고·축척 막대(바닥에서 약 20px)와 겹치지 않게 40px 띄운다(#1524).
        // 휴대폰은 시트 위에 붙어 다니고 로고는 하단 탭 뒤라 겹치지 않는다.
        className={`absolute left-4 ${docked ? 'pointer-events-auto bottom-10' : 'bottom-[calc(100%+12px)]'} press flex min-h-11 min-w-11 items-center gap-2`}
      >
        {/* 지도 위에 맨몸으로 서서 그림자로 띄운다. 휴대폰 48 · 태블릿 56 · PC 64. */}
        <span className="relative block drop-shadow-md">
          <MapPingo heading={heading} wave={text !== null} idle={idle} className="size-12 md:size-14 lg:size-16" />
        </span>
        {text && (
          // 폭은 오른쪽 지도 버튼에 닿지 않을 만큼만 — 넘치면 두 줄이 된다. 제안이 새로 오면 key 로 한 번 나타난다.
          <span
            key={text}
            className={`${speech ? 'enter-pop text-ink-900' : 'text-link'} relative flex min-h-9 max-w-[min(20rem,calc(100vw-140px))] items-center break-keep rounded-xl bg-surface px-3 py-1.5 text-left text-sm font-bold shadow-float transition-opacity ${
              fading ? 'opacity-0 duration-150' : 'opacity-100 delay-800 duration-300'
            }`}
          >
            {/* 말풍선 꼬리 — 핑고 쪽을 가리킨다. */}
            <span aria-hidden="true" className="absolute -left-1 top-1/2 size-2.5 -translate-y-1/2 rotate-45 bg-surface" />
            {text}
          </span>
        )}
      </button>
      {open && <AgentSheet mapId={mapId} onClose={() => setOpen(false)} />}
    </>
  )
}
