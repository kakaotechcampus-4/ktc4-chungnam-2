import type { Pin } from './model'

type PinKind = Pin['kind']

/** 물방울 핀. 뾰족한 끝(y=30)이 좌표를 가리키므로 오버레이의 yAnchor 는 1이어야 한다. */
const PIN_PATH = 'M12 2C7.6 2 4 5.6 4 10c0 6 8 20 8 20s8-14 8-20c0-4.4-3.6-8-8-8z'
const HEART = 'M12 14.2l-.6-.5C9.3 11.8 8 10.6 8 9.2 8 8.1 8.9 7.2 10 7.2c.6 0 1.2.3 1.6.7l.4.4.4-.4c.4-.4 1-.7 1.6-.7 1.1 0 2 .9 2 2 0 1.4-1.3 2.6-3.4 4.5l-.6.5z'

/**
 * 핀 3종(docs/design/colors.md 3절) — 종류는 **모양**으로, 색의 진하기는 **참여율**로 나타낸다.
 * - 일반: 빨강 실선 테두리 + 속은 참여율만큼 회색→빨강(oklch 로 섞어야 중간이 탁해지지 않는다)
 * - AI 추천: 빨강 점선 테두리 + 회색 속. 참여율을 넣지 않는다(올리기 전엔 나만 본다)
 * - 확정: 골드 채움 + 흰 테두리 3px + 그 바깥 갈색 1px + 그림자 + 갈색 ♥. 참여율과 무관하다.
 *   밝은 땅 위에선 흰 테두리가 묻혀서(실측 1.2:1) 갈색 선이 가시성을 맡는다(#299)
 * 구성원별 색 구분은 없다(#26).
 */
function shapeOf(kind: PinKind, ratio: number) {
  if (kind === '확정') {
    return { fill: 'var(--pin-confirmed)', stroke: 'var(--pin-confirmed-stroke)', width: 3, dash: 'none', heart: true }
  }
  const fill =
    kind === 'AI추천'
      ? 'var(--pin-fill-empty)'
      : `color-mix(in oklch, var(--pin-fill-full) ${Math.round(ratio * 100)}%, var(--pin-fill-empty))`
  return { fill, stroke: 'var(--pin-stroke)', width: 2.5, dash: kind === 'AI추천' ? '4 3' : 'none', heart: false }
}

/** var()·color-mix() 는 SVG 속성보다 style 에서 확실히 해석된다. */
export function createPinMarkerElement(pin: Pin, ratio: number, onClick: () => void): HTMLElement {
  const shape = shapeOf(pin.kind, ratio)

  const el = document.createElement('button')
  el.type = 'button'
  // 장소 이름은 setAttribute 로만 넣는다 — innerHTML 로 들어가면 이름이 마크업으로 해석된다.
  el.setAttribute('aria-label', `${pin.place_name ?? '이름 없는 핀'} · ${pin.kind} 핀`)
  el.style.cssText =
    'display:flex;align-items:flex-end;justify-content:center;width:44px;height:44px;padding:0;border:0;background:none;cursor:pointer;line-height:0;' +
    (pin.kind === '확정' ? 'filter:drop-shadow(var(--pin-confirmed-shadow));' : '')
  el.innerHTML = `
    <svg viewBox="0 0 24 32" width="30" height="38" aria-hidden="true">
      ${pin.kind === '확정' ? `<path d="${PIN_PATH}" stroke-linejoin="round" style="fill:none;stroke:var(--pin-confirmed-mark);stroke-width:5" />` : ''}
      <path d="${PIN_PATH}" stroke-linejoin="round"
            style="fill:${shape.fill};stroke:${shape.stroke};stroke-width:${shape.width};stroke-dasharray:${shape.dash}" />
      ${shape.heart ? `<path d="${HEART}" style="fill:var(--pin-confirmed-mark)" />` : ''}
    </svg>`
  el.addEventListener('click', onClick)
  return el
}
