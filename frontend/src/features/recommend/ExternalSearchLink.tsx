import { ExternalLink } from 'lucide-react'

import type { ExternalSearchDto } from './model'

/**
 * 「카카오맵에서 더 찾아보기」(#798) — 핑고에 결과가 없거나 적을 때 사람이 밖에서 직접 찾는 출구다. AI 추천 결과가 아니다.
 * 새 창으로 연다 — 앱 안 WebView 금지(카카오 약관). 검색어는 서버가 만든 그대로 함께 보여 준다.
 * 버튼 모양(색·크기)은 놓이는 자리가 정한다.
 */
export default function ExternalSearchLink({ search, className }: { search: ExternalSearchDto; className: string }) {
  return (
    <div className="space-y-1">
      <a href={search.url} target="_blank" rel="noopener noreferrer" className={className}>
        카카오맵에서 더 찾아보기 <ExternalLink size={16} aria-hidden="true" />
      </a>
      <p className="text-xs text-ink-500">검색어 ‘{search.query}’</p>
    </div>
  )
}
