import type { Pin } from './usePins'

type PinKind = NonNullable<Pin['kind']>

/**
 * 기획안 4절·9절 — 핀 종류는 3개뿐이고 **모양**으로 구분한다. 색으로 구분하지 않는다.
 * 구성원별 색 구분도 없다(#26에서 폐기).
 *
 * `Marker` 가 아니라 `CustomOverlay` 를 쓰는 이유가 여기 있다. Marker 는 이미지만 받아서
 * 점선 테두리를 PNG 3장으로 굽거나 data-URI 로 밀어넣어야 하고, 그러면 다크모드에서
 * 색이 안 따라온다. 인라인 SVG + CSS 변수면 테마가 저절로 따라온다.
 */
const SHAPE: Record<PinKind, { fill: string; stroke: string; dash: string }> = {
  '확정': { fill: 'var(--primary)', stroke: 'var(--primary)', dash: 'none' },
  '일반': { fill: 'var(--background)', stroke: 'var(--foreground)', dash: 'none' },
  'AI추천': { fill: 'var(--background)', stroke: 'var(--foreground)', dash: '4 3' },
}

/** 물방울 핀. 뾰족한 끝(y=30)이 좌표를 가리키므로 오버레이의 yAnchor 는 1이어야 한다. */
const PIN_PATH = 'M12 2C7.6 2 4 5.6 4 10c0 6 8 20 8 20s8-14 8-20c0-4.4-3.6-8-8-8z'

export function createPinMarkerElement(pin: Pin, onClick: () => void): HTMLElement {
  const kind = pin.kind ?? '일반'
  const shape = SHAPE[kind] ?? SHAPE['일반']

  const el = document.createElement('button')
  el.type = 'button'
  // 장소 이름은 setAttribute 로만 넣는다 — innerHTML 로 들어가면 이름이 마크업으로 해석된다.
  el.setAttribute('aria-label', `${pin.place_name ?? '이름 없는 핀'} · ${kind} 핀`)
  el.style.cssText =
    'display:block;width:26px;height:33px;padding:0;border:0;background:none;cursor:pointer;line-height:0'
  el.innerHTML = `
    <svg viewBox="0 0 24 32" width="26" height="33" aria-hidden="true">
      <path d="${PIN_PATH}" fill="${shape.fill}" stroke="${shape.stroke}"
            stroke-width="2" stroke-dasharray="${shape.dash}" stroke-linejoin="round" />
    </svg>`
  el.addEventListener('click', onClick)
  return el
}
