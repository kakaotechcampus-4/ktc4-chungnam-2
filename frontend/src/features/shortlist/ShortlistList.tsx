import { GripVertical } from 'lucide-react'

import Checkbox from '@/ui/Checkbox'

import DragGhost from './DragGhost'
import type { ShortlistItemDto } from './model'
import type { DropSpot } from './schedule'
import { useScheduleDrag } from './useScheduleDrag'

/**
 * 확정 리스트(Figma 7절) — 일정에 아직 넣지 않은 확정 장소다(2026-11-03). 순서는 일정이 정해서 여기서는 바꾸지 않는다.
 * 체크박스로 여러 곳을 골라 아래 막대에서 한 번에 그날로 넣는다(모든 화면, 키보드 포함). 넣은 곳은 이 목록에서 빠진다.
 * 넓은 화면에서 「일정 짜기」 패널이 열려 있으면(`onDrop`) ≡ 를 끌어 패널 날짜 칸에 놓아도 된다 — ≡ 는 손가락·마우스 전용이라 화면 읽기에서 뺀다.
 * 빼기는 「확정 해제」 하나다 — 핀 삭제가 아니라 확정 해제라서 '삭제'라고 부르지 않는다.
 */
export default function ShortlistList({
  items,
  checked,
  onCheck,
  onOpen,
  onRemove,
  onDrop,
}: {
  items: ShortlistItemDto[]
  checked: Set<string>
  onCheck: (pinId: string, on: boolean) => void
  onOpen: (pinId: string) => void
  onRemove: (item: ShortlistItemDto) => void
  onDrop?: (item: ShortlistItemDto, spot: DropSpot) => void
}) {
  return (
    <ul className="space-y-2">
      {items.map((item) => (
        <Row
          key={item.id}
          item={item}
          checked={checked.has(item.pin.id)}
          onCheck={(on) => onCheck(item.pin.id, on)}
          onOpen={() => onOpen(item.pin.id)}
          onRemove={() => onRemove(item)}
          onDrop={onDrop && ((spot) => onDrop(item, spot))}
        />
      ))}
    </ul>
  )
}

function Row({
  item,
  checked,
  onCheck,
  onOpen,
  onRemove,
  onDrop,
}: {
  item: ShortlistItemDto
  checked: boolean
  onCheck: (on: boolean) => void
  onOpen: () => void
  onRemove: () => void
  onDrop?: (spot: DropSpot) => void
}) {
  const name = item.pin.place_name ?? '이 장소'
  const { handlers, dragging, ghost } = useScheduleDrag(item.pin.id, (spot) => onDrop?.(spot))
  return (
    <li className={`rounded-xl border border-ink-200 bg-white py-1.5 pl-3 pr-1.5 ${dragging ? 'opacity-40' : ''}`}>
      <div className="flex items-center gap-2">
        {/* 상자만 보이는 칸(누르는 곳 44×44) — 이름은 화면 읽기용이다. 핀 이름은 옆의 상세 열기 버튼이다. */}
        <div className="-ml-1.5 w-11 shrink-0">
          <Checkbox checked={checked} onChange={onCheck}>
            <span className="sr-only">{name} 고르기</span>
          </Checkbox>
        </div>
        {/* 키보드·VoiceOver로도 열리게 버튼이다(검색 결과 줄과 같다, #959). */}
        <button type="button" onClick={onOpen} className="press -mx-1.5 min-w-0 flex-1 select-none rounded-md px-1.5 py-1 text-left">
          <p className="truncate font-bold text-ink-900">{name}</p>
          <p className="truncate text-xs text-ink-500">
            {item.pin.category}
            {item.pin.created_by_display_name && ` · ${item.pin.created_by_display_name}님이 찍은 핀`}
          </p>
        </button>
        {item.permissions.can_remove_from_shortlist && (
          <button type="button" onClick={onRemove} className="btn-text shrink-0 text-xs">
            확정 해제
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
