import { MessageCircle } from 'lucide-react'

import { kakaoLoginUrl } from './api'

/** 카카오 로그인 버튼(Figma 입구 화면). 문구는 「카카오로 시작하기」, 로그인이 실패하고 돌아왔으면 「다시 시도하기」. */
export default function KakaoButton({ retry = false }: { retry?: boolean }) {
  return (
    <a
      href={kakaoLoginUrl()}
      className="flex w-full items-center justify-center gap-2 rounded-xl bg-[#FEE500] py-3.5 font-semibold text-black/85"
    >
      <MessageCircle size={18} fill="currentColor" aria-hidden="true" /> {retry ? '카카오로 다시 시도하기' : '카카오로 시작하기'}
    </a>
  )
}
