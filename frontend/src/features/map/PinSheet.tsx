import type { Pin } from './usePins'

/**
 * 핀 상세 바텀시트 (#21).
 * 반응 UI(#17)는 이 안에 `PinReactions` 로 들어온다 — 그게 이 피처에서 두 사람이
 * 만나는 유일한 지점이라, 여기 말고 다른 곳에서는 붙이지 않는다.
 */
export default function PinSheet({ pin, onClose }: { pin: Pin; onClose: () => void }) {
  return (
    <aside className="fixed inset-x-0 bottom-14 rounded-t-xl border-t bg-background p-4 shadow-lg">
      <div className="flex items-start justify-between">
        <div>
          <p className="font-medium">{pin.place_name}</p>
          {/* 구성원별 색 구분은 없다(#26). "누가 찍었는지"는 여기서만 보여준다. */}
          <p className="text-xs text-muted-foreground">
            {pin.created_by_display_name} 님이 찍음
          </p>
        </div>
        <button type="button" onClick={onClose} className="text-sm text-muted-foreground">
          닫기
        </button>
      </div>
    </aside>
  )
}
