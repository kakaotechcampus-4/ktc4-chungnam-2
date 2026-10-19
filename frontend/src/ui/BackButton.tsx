import { ChevronLeft } from 'lucide-react'

/**
 * 시트 안 이전 화면(「‹ 마킹된 장소」 같은 것). 좌상단 흰 원 ‹(내 지도 목록)와 다르다 — Figma 뒤로가기 규칙.
 * 잠깐 하는 작업(검색·의견 입력)을 끝내는 건 이게 아니라 btn-text 「닫기」다.
 */
export default function BackButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="btn-text mb-2 flex items-center gap-0.5 text-body">
      <ChevronLeft size={14} aria-hidden="true" />
      {label}
    </button>
  )
}
