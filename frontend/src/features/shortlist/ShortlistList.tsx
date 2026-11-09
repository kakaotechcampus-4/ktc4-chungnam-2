import { GripVertical, Plus } from 'lucide-react'
import { authorName } from '@/features/map/model'
import UnknownName from '@/ui/UnknownName'

import DragGhost from './DragGhost'
import type { ShortlistItemDto } from './model'
import type { DropSpot } from './schedule'
import { useScheduleDrag } from './useScheduleDrag'

/**
 * 확정 리스트(Figma 7절) — 일정에 아직 넣지 않은 확정 장소다(2026-11-03). 순서는 일정이 정해서 여기서는 바꾸지 않는다.
 * 줄의 「넣기」를 누르면 위에서 고른 날(`dayLabel`) 끝에 바로 들어가고 이 목록에서 빠진다(모든 화면, 키보드 포함). 실수는 토스트의 「되돌리기」로 고친다.
 * 넓은 화면에서 「일정 짜기」 패널이 열려 있으면(`onDrop`) ≡ 를 끌어 패널 날짜 칸에 놓아도 된다 — ≡ 는 손가락·마우스 전용이라 화면 읽기에서 뺀다.
 * 「확정 해제」는 줄에 두지 않고 핀 상세에 있다 — 줄 버튼이 둘이면 누르는 곳이 좁아지고, 넣기와 헷갈린다.
 */
export default function ShortlistList({
  items,
  dayLabel,
  onPut,
  onOpen,
  onDrop,
  myId,
}: {
  items: ShortlistItemDto[]
  /** 넣을 날(「첫째 날」). 여행 날짜가 없으면 `onPut`도 없고 「넣기」를 그리지 않는다. */
  dayLabel: string
  onPut?: (item: ShortlistItemDto) => void
  onOpen: (pinId: string) => void
  onDrop?: (item: ShortlistItemDto, spot: DropSpot) => void
  /** 내 핀을 「내가 찍은 핀」으로 부르려고 받는다. */
  myId?: string
}) {
  return (
    <ul className="space-y-2">
      {items.map((item) => (
        <Row
          key={item.id}
          item={item}
          dayLabel={dayLabel}
          myId={myId}
          onPut={onPut && (() => onPut(item))}
          onOpen={() => onOpen(item.pin.id)}
          onDrop={onDrop && ((spot) => onDrop(item, spot))}
        />
      ))}
    </ul>
  )
}

function Row({
  item,
  dayLabel,
  onPut,
  onOpen,
  onDrop,
  myId,
}: {
  item: ShortlistItemDto
  dayLabel: string
  onPut?: () => void
  onOpen: () => void
  onDrop?: (spot: DropSpot) => void
  myId?: string
}) {
  const name = item.pin.place_name ?? '이 장소'
  const { handlers, dragging, ghost } = useScheduleDrag(item.pin.id, (spot) => onDrop?.(spot))
  return (
    <li className={`rounded-xl border border-ink-200 bg-surface py-1.5 pl-3 pr-1.5 ${dragging ? 'opacity-40' : ''}`}>
      <div className="flex items-center gap-2">
        {/* 키보드·VoiceOver로도 열리게 버튼이다(검색 결과 줄과 같다, #959). */}
        <button type="button" onClick={onOpen} className="press -mx-1.5 min-w-0 flex-1 select-none rounded-md px-1.5 py-1 text-left">
          <p className="truncate font-bold text-ink-900">{name}</p>
          <p className="truncate text-xs text-ink-500">
            {item.pin.category}
            {/* 핀 상세와 같은 말을 쓴다 — 내 핀을 「황경님이 찍은 핀」으로 부르지 않는다. */}
            {item.pin.created_by === myId ? ' · 내가 찍은 핀' : <UnknownName text={` · ${authorName(item.pin)}님이 찍은 핀`} />}
          </p>
        </button>
        {onPut && (
          <button type="button" onClick={onPut} aria-label={`${name} ${dayLabel}에 넣기`} className="btn-outline btn-sm shrink-0">
            <Plus size={16} aria-hidden="true" />
            넣기
          </button>
        )}
        {onDrop && (
          <span aria-hidden="true" className="flex size-11 shrink-0 cursor-grab touch-none items-center justify-center text-ink-400" {...handlers}>
            <GripVertical size={20} />
          </span>
        )}
      </div>
      {ghost && <DragGhost name={name} x={ghost.x} y={ghost.y} />}
    </li>
  )
}
