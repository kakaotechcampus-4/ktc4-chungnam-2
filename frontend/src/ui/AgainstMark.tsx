import { Ban } from 'lucide-react'

/**
 * 반대 기호. 용어는 「🚫 반대」로 고정(기획안 9절)이지만 이모지는 OS마다 모양이 다르고 CSS 색이 안 먹는다.
 * 화면에는 이 아이콘을 그리고, 뜻은 옆 글자「반대」나 aria-label 이 전한다(#299). 색은 currentColor.
 */
export default function AgainstMark({ size = 14 }: { size?: number }) {
  return <Ban size={size} strokeWidth={2.5} aria-hidden="true" className="inline-block shrink-0 align-[-0.125em]" />
}
