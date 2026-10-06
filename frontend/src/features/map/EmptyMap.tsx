import EmptyState from '@/ui/EmptyState'

/** 핀 0개(Figma 3절 '빈 지도', docs/errors.md MAP_EMPTY). v1 핀은 검색으로만 찍는다(#191). */
export default function EmptyMap() {
  return (
    <EmptyState
      title="아직 아무도 핀을 찍지 않았어요"
      action={
        <button type="button" onClick={() => document.getElementById('place-search')?.focus()} className="btn-outline px-4 py-2 text-sm">
          장소 검색하기
        </button>
      }
    >
      위 검색창에서 가게 이름을 찾아 핀을 찍어 보세요
    </EmptyState>
  )
}
