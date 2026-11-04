import { Heart } from 'lucide-react'

/**
 * 좋음 기호. 용어는 「♥ 좋음」으로 고정(기획안 9절)이지만 ♥ 글자는 OS·글꼴마다 모양과 굵기가 다르고, 일부 기기는 이모지로 그린다.
 * `AgainstMark`와 같은 크기·정렬로 그리고, 뜻은 옆 글자「좋음」이나 aria-label 이 전한다. 색은 currentColor.
 */
export default function LikeMark({ size = 14 }: { size?: number }) {
  return <Heart size={size} strokeWidth={2.5} fill="currentColor" aria-hidden="true" className="inline-block shrink-0 align-[-0.125em]" />
}
