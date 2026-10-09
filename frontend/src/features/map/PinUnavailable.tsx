/**
 * 주소로 들어왔는데 그 핀을 볼 수 없을 때 (#21).
 *
 * `GET /maps/{id}/pins` 는 남의 비공개 AI 후보를 애초에 내려주지 않는다(5-5-1).
 * 그래서 FE 가 받는 신호는 "목록에 없다" 하나뿐이고, 비공개인지 지워졌는지 구분할 방법이
 * 계약에 없다 — 둘 다 덮는 문구로 안내한다. (`docs/errors.md` 의 AI_PIN_PRIVATE 는
 * 404 로 정의돼 있지만 그걸 돌려줄 단건 조회 엔드포인트가 없다. 루트에 보고 대상.)
 */
export default function PinUnavailable({ onClose }: { onClose: () => void }) {
  return (
    <div role="status" className="mb-3 flex items-start justify-between gap-3 rounded-xl border border-ink-200 p-4">
      <div>
        <p className="font-medium text-ink-900">이 핀은 지금 볼 수 없어요</p>
        <p className="mt-1 text-xs text-ink-500">아직 지도에 올라오지 않은 AI 추천이거나, 지워진 핀이에요.</p>
      </div>
      <button type="button" onClick={onClose} className="shrink-0 text-sm text-ink-500">
        닫기
      </button>
    </div>
  )
}
