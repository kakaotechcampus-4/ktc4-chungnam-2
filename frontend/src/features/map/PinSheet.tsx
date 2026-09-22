import { useEffect, type ReactNode } from 'react'

import type { Pin } from './usePins'

/** 용어 고정(기획안 9절). 반응은 이 4개 말고 다른 이름으로 부르지 않는다. */
const REACTION_LABEL = {
  like: '♥ 좋음',
  neutral: '△ 조율 필요',
  against: '🚫 반대',
} as const

function SheetShell({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  return (
    <aside
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-x-0 bottom-14 z-30 max-h-[60vh] overflow-y-auto rounded-t-xl border-t bg-background p-4 shadow-lg"
    >
      {children}
    </aside>
  )
}

/**
 * 핀 상세 (#21).
 * 반응 버튼(#17)은 아래 표시된 자리에 들어온다 — 이 피처에서 두 사람이 만나는 유일한 지점이라
 * 다른 곳에는 붙이지 않는다.
 */
export default function PinSheet({ pin, onClose }: { pin: Pin; onClose: () => void }) {
  const summary = pin.reaction_summary

  return (
    <SheetShell title={pin.place_name ?? '핀 상세'} onClose={onClose}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-medium">{pin.place_name}</p>
          <p className="text-xs text-muted-foreground">
            {/* 구성원별 색 구분은 없다(#26). "누가 찍었는지"는 여기서만 보여준다. */}
            {pin.category} · {pin.kind} 핀 · {pin.created_by_display_name} 님이 찍음
          </p>
        </div>
        <button type="button" onClick={onClose} className="shrink-0 text-sm text-muted-foreground">
          닫기
        </button>
      </div>

      {summary && (
        <dl className="mt-3 flex gap-4 text-xs">
          {(['like', 'neutral', 'against'] as const).map((type) => (
            <div key={type} className="flex gap-1">
              <dt className="text-muted-foreground">{REACTION_LABEL[type]}</dt>
              <dd className="font-medium tabular-nums">{summary[type] ?? 0}</dd>
            </div>
          ))}
        </dl>
      )}

      {/* 가드레일 5 — 대안 핀의 이유·조건별 충족 체크는 게시된 뒤에도 계속 붙어 있어야 한다. */}
      {pin.checks && pin.checks.length > 0 && (
        <ul className="mt-3 space-y-1 border-t pt-3">
          {pin.checks.map((check) => (
            <li key={check.fact_key} className="flex items-start gap-2 text-xs">
              <span aria-hidden="true">{check.passed ? '✓' : '✗'}</span>
              <span className="flex-1">{check.label}</span>
              {/* unknown_policy 가 pass+needs_check 인 취향 조건. 통과지만 사람이 확인해야 한다. */}
              {check.needs_check && <span className="text-muted-foreground">직접 확인 필요</span>}
            </li>
          ))}
        </ul>
      )}

      {/* 반응 등록 UI 자리 (#17). 140자 카운터·반대 시 사유 필수는 그 이슈에서 붙인다. */}
    </SheetShell>
  )
}

/**
 * 주소로 들어왔는데 그 핀을 볼 수 없을 때 (#21).
 *
 * `GET /maps/{id}/pins` 는 남의 비공개 AI 후보를 애초에 내려주지 않는다(5-5-1).
 * 그래서 FE 가 받는 신호는 "목록에 없다" 하나뿐이고, 비공개인지 지워졌는지 구분할 방법이
 * 계약에 없다 — 둘 다 덮는 문구로 안내한다. (`docs/errors.md` 의 AI_PIN_PRIVATE 는
 * 404 로 정의돼 있지만 그걸 돌려줄 단건 조회 엔드포인트가 없다. 루트에 보고 대상.)
 */
export function PinUnavailableSheet({ onClose }: { onClose: () => void }) {
  return (
    <SheetShell title="볼 수 없는 핀" onClose={onClose}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-medium">이 핀은 지금 볼 수 없어요</p>
          <p className="mt-1 text-xs text-muted-foreground">
            아직 지도에 올라오지 않은 AI 추천이거나, 지워진 핀이에요.
          </p>
        </div>
        <button type="button" onClick={onClose} className="shrink-0 text-sm text-muted-foreground">
          닫기
        </button>
      </div>
    </SheetShell>
  )
}
