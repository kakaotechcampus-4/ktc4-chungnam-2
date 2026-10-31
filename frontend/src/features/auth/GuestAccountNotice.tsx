import type { ReactNode } from 'react'

import KakaoButton from './KakaoButton'

/**
 * 게스트에게 카카오 계정 만들기를 권하는 상자(#485). 계정 시트·지도 정보의 계정 줄 아래, 그리고 게스트가 못 쓰는
 * AI 실행 버튼 자리(추천 받기·AI 코스 짜기, #432)에 둔다. 문구는 `children`으로 바꾼다. 바깥 여백은 놓는 쪽이 준다.
 * 카카오로 로그인하면 서버가 게스트 기록을 그 계정으로 합친다(#560) — 결과는 돌아온 주소의 `guest_merged`로 알린다.
 */
export default function GuestAccountNotice({ children }: { children?: ReactNode }) {
  return (
    <div className="space-y-2 rounded-xl bg-ink-50 p-3">
      <p className="break-keep text-sm text-ink-700">
        {children ?? '카카오로 계정을 만들면 지금까지 남긴 핀과 의견이 그대로 이어지고, 새 지도도 만들 수 있어요.'}
      </p>
      <KakaoButton label="카카오로 계정 만들기" />
    </div>
  )
}
