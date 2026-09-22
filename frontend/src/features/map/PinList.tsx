import type { Pin } from './usePins'

/**
 * 핀 목록. 지금은 목 서버가 살아 있는지 확인하는 텍스트 나열까지만이다 —
 * 바텀시트 목록 UI·구성원별 보기(`created_by` 필터)는 #19 에서 이 파일을 채운다.
 */
export default function PinList({
  pins,
  onSelect,
}: {
  pins: Pin[]
  onSelect: (pinId: string | null) => void
}) {
  return (
    <ul className="space-y-1">
      {pins.map((pin) => (
        <li key={pin.id}>
          <button
            type="button"
            onClick={() => onSelect(pin.id ?? null)}
            className="w-full rounded-md border px-3 py-2 text-left text-sm hover:bg-accent"
          >
            <span className="font-medium">{pin.place_name}</span>
            <span className="ml-2 text-xs text-muted-foreground">
              {pin.category} · {pin.kind}
            </span>
          </button>
        </li>
      ))}
    </ul>
  )
}
