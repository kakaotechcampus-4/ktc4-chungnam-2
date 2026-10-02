import Pingo from '@/ui/Pingo'

/** 핀 0개(Figma 3절 '빈 지도', docs/errors.md MAP_EMPTY). v1 핀은 검색으로만 찍는다(#191). */
export default function EmptyMap() {
  return (
    <div className="flex flex-col items-center py-6 text-center">
      <Pingo size={56} />
      <p className="mt-3 font-semibold text-ink-900">아직 아무도 핀을 찍지 않았어요</p>
      <p className="mt-1 text-sm text-ink-500">위 검색창에서 가게 이름을 찾아 핀을 찍어 보세요</p>
      <button
        type="button"
        onClick={() => document.getElementById('place-search')?.focus()}
        className="mt-4 rounded-lg border border-brand-600 px-4 py-2 text-sm font-semibold text-brand-600"
      >
        장소 검색하기
      </button>
    </div>
  )
}
