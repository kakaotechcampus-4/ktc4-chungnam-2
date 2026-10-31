import { MessageCircle } from 'lucide-react'

import { kakaoLoginUrl } from './api'

/**
 * 카카오 로그인 버튼(Figma 입구 화면). 문구는 「카카오로 시작하기」, 로그인이 실패하고 돌아왔으면 「다시 시도하기」.
 * 게스트 전환(#560)도 같은 주소로 가기만 하면 서버가 게스트 기록을 합친다 — 그때 문구만 `label`로 바꾼다.
 */
export default function KakaoButton({ retry = false, label }: { retry?: boolean; label?: string }) {
  return (
    <a
      href={kakaoLoginUrl()}
      className="btn-lg w-full rounded-xl bg-[#FEE500] font-semibold text-black/85"
    >
      <MessageCircle size={20} fill="currentColor" aria-hidden="true" /> {label ?? (retry ? '카카오로 다시 시도하기' : '카카오로 시작하기')}
    </a>
  )
}
