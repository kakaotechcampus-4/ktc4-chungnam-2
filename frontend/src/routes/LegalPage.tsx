import { Link } from 'react-router'
import { ChevronLeft } from 'lucide-react'

import { LEGAL_DOCS, LEGAL_META, type LegalDocKey } from '@/features/legal/docs'

/** 이용약관·개인정보처리방침·위치기반서비스 이용약관(#601). 로그인 화면의 약관 목록이 연다. 본문은 `features/legal/docs.ts`. */
export default function LegalPage({ doc }: { doc: LegalDocKey }) {
  const { title, intro, sections } = LEGAL_DOCS[doc]
  const meta: [string, string][] = [
    ['운영', LEGAL_META.operator],
    // 위치 약관은 같은 사람을 위치정보 관리책임자로 적는다(위치정보법).
    [doc === 'location' ? '위치정보 관리책임자' : '개인정보 보호책임자', LEGAL_META.officer],
    ['연락처', LEGAL_META.contact],
    ['시행일', LEGAL_META.effectiveDate],
  ]
  return (
    <main className="mx-auto min-h-dvh w-full max-w-[480px] bg-ink-50 px-4 pb-10 pt-4">
      <header className="mb-6 flex items-center gap-3">
        <Link to="/" aria-label="처음 화면으로" className="hit-44 flex size-8 shrink-0 items-center justify-center rounded-full bg-white shadow-float">
          <ChevronLeft size={20} />
        </Link>
        <h1 className="text-2xl font-bold break-keep text-ink-900">{title}</h1>
      </header>
      <p className="text-body break-keep text-ink-700">{intro}</p>
      {sections.map((section) => (
        <section key={section.heading} className="mt-6">
          <h2 className="text-sm font-bold text-ink-900">{section.heading}</h2>
          {section.blocks.map((block, i) =>
            typeof block === 'string' ? (
              <p key={i} className="text-body mt-2 break-keep text-ink-700">
                {block}
              </p>
            ) : (
              <ul key={i} className="text-body mt-2 list-disc space-y-1 break-keep pl-5 text-ink-700">
                {block.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ),
          )}
        </section>
      ))}
      <dl className="text-body mt-8 space-y-1 border-t border-ink-200 pt-4 text-ink-600">
        {meta.map(([label, value]) => (
          <div key={label} className="flex gap-2">
            <dt className="shrink-0 font-semibold">{label}</dt>
            <dd>{value || '정식 공개 전에 정합니다'}</dd>
          </div>
        ))}
      </dl>
    </main>
  )
}
