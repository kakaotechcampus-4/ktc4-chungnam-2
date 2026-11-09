import { useState } from 'react'

import CategoryIcon from '@/ui/CategoryIcon'

import type { Pin } from './model'
import { usePinPhotosQuery } from './queries'

/**
 * 장소 줄 왼쪽 56px 사진 칸(AI 코스 날짜별 카드). 핀 상세와 같은 블로그 사진(#1157)의 첫 장이고,
 * 출처와 나머지 사진은 줄을 눌러 여는 핀 상세가 보여 준다. 사진이 없거나 못 받으면 카테고리 아이콘이다.
 * 이름이 옆에 있어 그림은 aria-hidden 이다.
 */
export default function PinThumb({ pin }: { pin: Pin }) {
  const photos = usePinPhotosQuery(pin)
  const [broken, setBroken] = useState(false)
  const src = photos.data?.[0]?.thumbnail_url
  // 실시간 핀은 사진을 부르지 않는다(쿼리가 꺼져 있어 isPending 이 계속 참이다).
  const waiting = photos.isPending && pin.source !== 'live'
  return (
    <span
      aria-hidden="true"
      className={`flex size-14 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-ink-100 ${waiting ? 'animate-pulse motion-reduce:animate-none' : ''}`}
    >
      {src && !broken ? (
        <img src={src} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setBroken(true)} className="size-full object-cover" />
      ) : (
        !waiting && <CategoryIcon category={pin.category} />
      )}
    </span>
  )
}
