/**
 * 카테고리 아이콘의 선 경로 — 검색 결과 핀(pinMarker, React 밖)과 목록 카드(이 컴포넌트)가 같은 모양을 쓴다.
 * lucide(ISC) 아이콘의 선 경로를 옮겨 적었다: 음식점 utensils · 카페 coffee · 관광지 camera · 숙소 bed · 기타 map-pin.
 */
const CATEGORY_ICON_PATHS: Record<string, string> = {
  음식점: '<path d="M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2"/><path d="M7 2v20"/><path d="M21 15V2a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3Zm0 0v7"/>',
  카페: '<path d="M10 2v2"/><path d="M14 2v2"/><path d="M16 8a1 1 0 0 1 1 1v8a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4V9a1 1 0 0 1 1-1h14a4 4 0 1 1 0 8h-1"/><path d="M6 2v2"/>',
  관광지:
    '<path d="M13.997 4a2 2 0 0 1 1.76 1.05l.486.9A2 2 0 0 0 18.003 7H20a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h1.997a2 2 0 0 0 1.759-1.048l.489-.904A2 2 0 0 1 10.004 4z"/><circle cx="12" cy="13" r="3"/>',
  숙소: '<path d="M2 20v-8a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v8"/><path d="M4 10V6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v4"/><path d="M12 4v6"/><path d="M2 18h20"/>',
  기타: '<path d="M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0"/><circle cx="12" cy="10" r="3"/>',
}

export const categoryIconPath = (category: string | undefined | null) => CATEGORY_ICON_PATHS[category ?? ''] ?? CATEGORY_ICON_PATHS['기타']

/**
 * 목록 카드 왼쪽의 카테고리 칸(#1454) — ink-100 면 36px + ink-600 선 아이콘 20px.
 * 카테고리 이름은 옆 메타 줄이 이미 읽어 주므로 아이콘은 aria-hidden 이다.
 * 경로는 위의 고정 문자열뿐이라 innerHTML 로 넣어도 사용자 글이 섞이지 않는다.
 */
export default function CategoryIcon({ category }: { category: string }) {
  return (
    <span aria-hidden="true" className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-ink-100 text-ink-600">
      <svg
        viewBox="0 0 24 24"
        width={20}
        height={20}
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        dangerouslySetInnerHTML={{ __html: categoryIconPath(category) }}
      />
    </span>
  )
}
