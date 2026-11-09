import { useState } from 'react'
import { CircleHelp } from 'lucide-react'

import WelcomeScene from '@/features/onboarding/WelcomeScene'
import MenuPopover from '@/features/shell/MenuPopover'

/** 손이 하는 일 → 지도가 하는 일. 판단은 `mapTap`·지도 자리 메뉴(#1549, #1613)이고 여기는 그 뜻만 적는다. */
const ROWS = {
  mouse: [
    { how: '클릭', text: '누른 자리가 지도 가운데로 와요' },
    { how: '우클릭', text: '「신규 핀 찍기」로 그 근처 장소를 찾아 핀을 찍어요' },
    { how: '핀 끌기', text: '핀을 눌러 끌어 「삭제하기」 칸에 놓으면 지워요' },
  ],
  touch: [
    { how: '짧게 누르기', text: '누른 자리가 지도 가운데로 와요' },
    { how: '길게 누르기', text: '원이 다 차면 「신규 핀 찍기」로 그 근처 장소를 찾아 핀을 찍어요' },
    { how: '핀 끌기', text: '핀을 길게 눌러 끌어 「삭제하기」 칸에 놓으면 지워요' },
  ],
}

/**
 * 지도 위 카테고리 칩 줄 끝 「?」(#1613). 지도 버튼 묶음에 두면 묶음이 높아져 작은 휴대폰에서 묶음과 핑고 AI 조언이 숨어서 칩 줄로 옮겼다. 빈 지도 누르기와 핀 찍는 법을 움직이는 장면으로 보인다.
 * 처음 한 번 뜨는 토스트를 놓친 사람도 언제든 찾게 한다. 마우스면 클릭·우클릭, 터치면 짧게·길게 누르기다 —
 * 첫 안내 토스트(`showMapMenuHintOnce`)와 같은 기준(`pointer: fine`)이라 마우스를 단 태블릿은 마우스 쪽을 본다.
 */
export default function MapGestureHelp() {
  const [touch] = useState(() => !window.matchMedia?.('(pointer: fine)').matches)
  const rows = ROWS[touch ? 'touch' : 'mouse']
  return (
    <MenuPopover
      label="지도 쓰는 법"
      trigger={
        <button
          type="button"
          aria-label="지도 쓰는 법 보기"
          title="지도 쓰는 법"
          className="chip hit-44 pointer-events-auto px-2 text-link shadow-float"
        >
          <CircleHelp size={16} aria-hidden="true" />
        </button>
      }
    >
      <p className="text-sm font-bold text-ink-900">지도 쓰는 법</p>
      <WelcomeScene kind={touch ? 'mapTouch' : 'mapMouse'} className="mt-3 w-full" />
      <dl className="mt-3 space-y-2 text-body">
        {rows.map((r) => (
          <div key={r.how} className="flex gap-2">
            <dt className="w-[5.5rem] shrink-0 font-bold text-ink-900">{r.how}</dt>
            <dd className="break-keep text-ink-700">{r.text}</dd>
          </div>
        ))}
      </dl>
    </MenuPopover>
  )
}
