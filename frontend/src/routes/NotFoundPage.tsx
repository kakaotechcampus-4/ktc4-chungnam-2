import { Link } from 'react-router'

import EmptyState from '@/ui/EmptyState'
import EntryFrame from '@/ui/EntryFrame'

/**
 * 없는 주소(#1677). 서버는 화면 주소를 몰라 200을 주니, 구글이 이 화면을 색인하지 않게 noindex를 단다(구글이 SPA에 권하는 방법).
 * ponytail: JS를 돌리지 않는 크롤러에게는 여전히 200이다. 막으려면 Caddy에 화면 주소 목록을 두고 나머지를 404로 준다.
 */
export default function NotFoundPage() {
  return (
    <EntryFrame as="div" className="bg-ink-50 px-4 pb-6">
      <title>페이지를 찾을 수 없어요 | 핑고핑고</title>
      <meta name="robots" content="noindex" />
      <div className="flex flex-1 flex-col justify-center">
        <EmptyState mood="sad" title="페이지를 찾을 수 없어요">
          주소가 바뀌었거나 없는 페이지예요
        </EmptyState>
      </div>
      <Link to="/" className="btn-primary btn-lg md:mt-6">
        처음 화면으로
      </Link>
    </EntryFrame>
  )
}
