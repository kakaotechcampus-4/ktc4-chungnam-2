import EmptyState from '@/ui/EmptyState'

/** 핀 0개(Figma 3절 '빈 지도', docs/errors.md MAP_EMPTY). v1 핀은 검색으로만 찍는다(#191). */
export default function EmptyMap() {
  return (
    <EmptyState
      title="아직 지도에 핀이 없어요"
      action={
        <button type="button" onClick={() => document.getElementById('place-search')?.focus()} className="btn-outline btn-md">
          장소 검색하기
        </button>
      }
    >
      검색창에서 가고 싶은 장소를 찾아 첫 핀을 찍어 보세요
    </EmptyState>
  )
}
