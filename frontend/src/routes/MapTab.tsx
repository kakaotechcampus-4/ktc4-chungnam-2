import { useQuery } from '@tanstack/react-query'
import type { components } from '@pingo/contracts/src/types/api'

import { ApiError, api } from '@/api'
import { useUiStore } from '@/store'

type Pin = components['schemas']['Pin']

/** 목 서버 시드 지도. 지도 선택·초대(#4)가 붙으면 라우트 파라미터로 바뀐다. */
const MAP_ID = 'map_1'

export default function MapTab() {
  const selectedPinId = useUiStore((s) => s.selectedPinId)
  const selectPin = useUiStore((s) => s.selectPin)

  const { data: pins, isPending, error } = useQuery({
    queryKey: ['pins', MAP_ID],
    queryFn: () => api<Pin[]>(`/maps/${MAP_ID}/pins`),
  })

  const selectedPin = pins?.find((pin) => pin.id === selectedPinId)

  return (
    <div className="p-4">
      {/* 카카오맵 SDK 실연동은 #20. 여기는 목 서버가 살아 있는지 확인하는 텍스트 나열까지만. */}
      <div className="mb-4 flex h-40 items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground">
        지도 자리 (#20)
      </div>

      {isPending && <p className="text-sm text-muted-foreground">핀을 불러오는 중…</p>}

      {error && (
        <p className="text-sm text-destructive">
          핀을 불러오지 못했어요
          {error instanceof ApiError && <span className="ml-1 font-mono text-xs">({error.code})</span>}
        </p>
      )}

      {pins?.length === 0 && (
        // docs/errors.md MAP_EMPTY. 입력 경로 3개 안내는 #16.
        <p className="text-sm text-muted-foreground">아직 아무도 핀을 찍지 않았어요</p>
      )}

      <ul className="space-y-1">
        {pins?.map((pin) => (
          <li key={pin.id}>
            <button
              type="button"
              onClick={() => selectPin(pin.id ?? null)}
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

      {/* 바텀시트 자리. 검색(#16)·핀목록(#19)·핀상세(#21)가 여기로 들어온다. */}
      {selectedPin && (
        <aside className="fixed inset-x-0 bottom-14 rounded-t-xl border-t bg-background p-4 shadow-lg">
          <div className="flex items-start justify-between">
            <div>
              <p className="font-medium">{selectedPin.place_name}</p>
              <p className="text-xs text-muted-foreground">
                {selectedPin.created_by_display_name} 님이 찍음
              </p>
            </div>
            <button
              type="button"
              onClick={() => selectPin(null)}
              className="text-sm text-muted-foreground"
            >
              닫기
            </button>
          </div>
        </aside>
      )}
    </div>
  )
}
