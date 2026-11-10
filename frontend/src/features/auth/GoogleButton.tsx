import { googleLoginUrl } from './api'

/**
 * 구글 로그인 버튼(#1514). 카카오 버튼 아래에 같은 크기로 둔다 — 흰 바탕 + ink-200 테두리 + 구글 「G」 로고(구글 브랜드 가이드).
 * 게스트 전환도 카카오처럼 같은 주소로 가기만 하면 서버가 게스트 기록을 합친다 — 그때 문구만 `label`로 바꾼다.
 */
export default function GoogleButton({ label }: { label?: string }) {
  return (
    <a href={googleLoginUrl()} className="btn-lg w-full rounded-xl border border-ink-200 bg-surface font-semibold text-ink-900">
      <GoogleG /> {label ?? 'Google로 시작하기'}
    </a>
  )
}

/** 구글 「G」 로고. 브랜드 표시라 색을 바꾸지 않는다. */
function GoogleG() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  )
}
