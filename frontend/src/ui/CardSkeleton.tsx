import OfflineState from './OfflineState'
import Skeleton, { Bone } from './Skeleton'
import { useOnline } from './useOnline'

/**
 * 불러오는 중(Figma '불러오는 중') — 글자 대신 카드 모양 자리를 먼저 보여 준다. 핀 목록·내 지도 목록·일정·확정 리스트·조언이 쓴다.
 * 카드 모양은 화면 읽기에 숨긴다. `label`을 주면 그 글을 화면 읽기에만 알린다 — 옆에 「불러오는 중」 글이 따로 없는 자리다.
 */
export default function CardSkeleton({ count = 3, label }: { count?: number; label?: string }) {
  // 목록 자리라 한 줄 대신 핑고 빈 화면이다(#1722).
  if (!useOnline()) return <OfflineState />
  return (
    <Skeleton label={label}>
      <ul className="space-y-2.5">
        {Array.from({ length: count }, (_, i) => (
          <li key={i} className="space-y-2 rounded-xl border border-ink-200 bg-surface p-3.5">
            <Bone className="h-4 w-2/3" />
            <Bone className="h-3 w-1/2" />
            <Bone className="h-3 w-1/3" />
          </li>
        ))}
      </ul>
    </Skeleton>
  )
}
