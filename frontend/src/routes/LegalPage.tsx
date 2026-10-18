import { Link } from 'react-router'
import { ChevronLeft } from 'lucide-react'

/**
 * 이용약관·개인정보처리방침(#602). 로그인 화면의 동의 줄이 연다.
 * 문서는 PM이 준비 중이라(#601) 받기 전까지는 안내 한 줄만 보인다.
 */
export default function LegalPage({ title }: { title: string }) {
  return (
    <main className="mx-auto min-h-dvh w-full max-w-[480px] bg-ink-50 px-4 pb-6 pt-4">
      <header className="mb-6 flex items-center gap-3">
        <Link to="/" aria-label="처음 화면으로" className="hit-44 flex size-8 items-center justify-center rounded-full bg-white shadow-sm">
          <ChevronLeft size={20} />
        </Link>
        <h1 className="text-2xl font-bold text-ink-900">{title}</h1>
      </header>
      <p className="text-sm text-ink-600">아직 준비 중인 문서예요. 정식으로 공개하기 전에 이 자리에 올려 둘게요.</p>
    </main>
  )
}
