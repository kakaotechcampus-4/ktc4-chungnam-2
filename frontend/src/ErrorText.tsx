import { CircleAlert } from 'lucide-react'

import { ApiError } from '@/api'
import Sentences from '@/ui/Sentences'

/** 실패 문구 + 에러 코드. 코드는 BE·목 서버와 맞춰 볼 때 쓰려고 작게 붙인다. */
export default function ErrorText({ message, error }: { message: React.ReactNode; error: unknown }) {
  return (
    // 경고 기호 + 굵은 글자 — 주의색 글자만으로는 오류로 읽히지 않았다(#1447).
    <p className="flex items-start gap-1.5 text-sm font-semibold text-warn-text">
      <CircleAlert size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
      <span>
        {typeof message === 'string' ? <Sentences text={message} /> : message}
        {error instanceof ApiError && <span className="ml-1 font-mono text-xs font-normal">({error.code})</span>}
      </span>
    </p>
  )
}
