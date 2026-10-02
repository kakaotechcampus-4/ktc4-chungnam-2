import { ApiError } from '@/api'

/** 실패 문구 + 에러 코드. 코드는 BE·목 서버와 맞춰 볼 때 쓰려고 작게 붙인다. */
export default function ErrorText({ message, error }: { message: React.ReactNode; error: unknown }) {
  return (
    <p className="text-sm text-warn-text">
      {message}
      {error instanceof ApiError && <span className="ml-1 font-mono text-xs">({error.code})</span>}
    </p>
  )
}
