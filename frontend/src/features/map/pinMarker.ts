import type { PlaceSearchResultDto } from '@/features/search/model'
import { PINGO_MARK } from '@/ui/pingoMark'

import type { Pin } from './model'

type PinKind = Pin['kind']

/** 물방울 핀. 뾰족한 끝(y=30)이 좌표를 가리키므로 오버레이의 yAnchor 는 1이어야 한다. */
const PIN_PATH = 'M12 2C7.6 2 4 5.6 4 10c0 6 8 20 8 20s8-14 8-20c0-4.4-3.6-8-8-8z'
const HEART = 'M12 14.2l-.6-.5C9.3 11.8 8 10.6 8 9.2 8 8.1 8.9 7.2 10 7.2c.6 0 1.2.3 1.6.7l.4.4.4-.4c.4-.4 1-.7 1.6-.7 1.1 0 2 .9 2 2 0 1.4-1.3 2.6-3.4 4.5l-.6.5z'

/**
 * 지도 위 핀은 모양 2가지다 — 색의 진하기는 **참여율**로 나타낸다.
 * - 일반·AI 추천: 빨강 실선 테두리 + 속은 참여율만큼 회색→빨강(oklch 로 섞어야 중간이 탁해지지 않는다)
 *   + 머리 가운데 진한 빨간 점. AI 추천은 「지도에 올리기」로 모두의 핀이 된 뒤라 일반 핀과 같게 그린다.
 *   올리기 전 후보만 핑고 핀으로 따로 그린다(createCandidateMarkerElement).
 * - 확정: 골드 채움 + 흰 테두리 3px + 그 바깥 갈색 윤곽선 1px + 갈색 ♥. 참여율과 무관하다.
 *   밝은 땅 위에선 흰 테두리가 묻혀서(실측 1.2:1) 갈색 윤곽선이 가시성을 맡는다(#299). 그림자는 없다 — 이름표처럼 윤곽선으로 가른다
 * 구성원별 색 구분은 없다(#26).
 */
function shapeOf(kind: PinKind, ratio: number) {
  if (kind === '확정') {
    return { fill: 'var(--pin-confirmed)', stroke: 'var(--pin-confirmed-stroke)', width: 3, heart: true }
  }
  const fill = `color-mix(in oklch, var(--pin-fill-full) ${Math.round(ratio * 100)}%, var(--pin-fill-empty))`
  return { fill, stroke: 'var(--pin-stroke)', width: 2.5, heart: false }
}

/** var()·color-mix() 는 SVG 속성보다 style 에서 확실히 해석된다. */
export function createPinMarkerElement(pin: Pin, ratio: number, onClick: () => void): HTMLElement {
  const shape = shapeOf(pin.kind, ratio)

  const el = document.createElement('button')
  el.type = 'button'
  // 장소 이름은 setAttribute 로만 넣는다 — innerHTML 로 들어가면 이름이 마크업으로 해석된다.
  el.setAttribute('aria-label', `${pin.place_name ?? '이름 없는 핀'} · ${pin.kind} 핀`)
  el.style.cssText =
    'display:flex;align-items:flex-end;justify-content:center;width:44px;height:44px;padding:0;border:0;background:none;cursor:pointer;line-height:0;'
  el.innerHTML = `
    <svg viewBox="0 0 24 32" width="30" height="38" aria-hidden="true">
      ${pin.kind === '확정' ? `<path d="${PIN_PATH}" stroke-linejoin="round" style="fill:none;stroke:var(--pin-confirmed-mark);stroke-width:5" />` : ''}
      <path d="${PIN_PATH}" stroke-linejoin="round"
            style="fill:${shape.fill};stroke:${shape.stroke};stroke-width:${shape.width}" />
      ${shape.heart ? `<path d="${HEART}" style="fill:var(--pin-confirmed-mark)" />` : `<circle cx="12" cy="10" r="3.2" style="fill:var(--pin-dot)" />`}
    </svg>`
  el.addEventListener('click', onClick)
  return el
}

type SearchCategory = NonNullable<PlaceSearchResultDto['category']>

/** 검색 핀 안의 카테고리 아이콘. lucide(ISC) 아이콘의 선 경로를 옮겨 적었다 — 마커는 React 밖이라 컴포넌트를 못 쓴다. */
const CATEGORY_ICON: Record<SearchCategory, string> = {
  음식점: '<path d="M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2"/><path d="M7 2v20"/><path d="M21 15V2a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3Zm0 0v7"/>',
  카페: '<path d="M10 2v2"/><path d="M14 2v2"/><path d="M16 8a1 1 0 0 1 1 1v8a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4V9a1 1 0 0 1 1-1h14a4 4 0 1 1 0 8h-1"/><path d="M6 2v2"/>',
  관광지:
    '<path d="M13.997 4a2 2 0 0 1 1.76 1.05l.486.9A2 2 0 0 0 18.003 7H20a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h1.997a2 2 0 0 0 1.759-1.048l.489-.904A2 2 0 0 1 10.004 4z"/><circle cx="12" cy="13" r="3"/>',
  숙소: '<path d="M2 20v-8a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v8"/><path d="M4 10V6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v4"/><path d="M12 4v6"/><path d="M2 18h20"/>',
  기타: '<path d="M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0"/><circle cx="12" cy="10" r="3"/>',
}

/**
 * 장소 검색 결과 — 빨간 원 + 흰 카테고리 아이콘, 아래 짧은 꼬리 끝이 좌표다(네이버 검색 핀처럼).
 * 물방울 핀과 모양이 달라서 아직 지도에 없는 곳으로 읽힌다. 숫자는 지도에 적지 않는다.
 * 고른 결과는 한 번 튀어 커진다(pin-bounce). 후광·이름 말풍선은 MapCanvas 가 markSelected 로 단다.
 * 핑고는 붙이지 않는다 — 핑고가 나오면 AI가 말한 것이라(PRODUCT.md) 검색 결과엔 어울리지 않는다.
 */
export function createSearchMarkerElement(
  r: { n: number; name: string; category?: SearchCategory; selected: boolean },
  onClick: () => void,
): HTMLElement {
  const el = document.createElement('button')
  el.type = 'button'
  el.setAttribute('aria-label', [`검색 결과 ${r.n}번`, r.name, r.category].filter(Boolean).join(' · '))
  if (r.selected) el.setAttribute('aria-current', 'true')
  el.style.cssText =
    'display:flex;align-items:flex-end;justify-content:center;width:44px;height:44px;padding:0;border:0;background:none;cursor:pointer;line-height:0;'
  el.innerHTML = `
    <svg viewBox="0 0 32 38" width="32" height="38" aria-hidden="true"
         style="filter:drop-shadow(0 1px 2px rgba(20,22,31,.3))"${r.selected ? ' class="pin-bounce"' : ''}>
      <path d="M11 26L16 36.5L21 26Z" stroke-linejoin="round" style="fill:var(--pin-stroke);stroke:#fff;stroke-width:2" />
      <circle cx="16" cy="16" r="14" style="fill:var(--pin-stroke);stroke:#fff;stroke-width:2" />
      <g transform="translate(9.5 9.5) scale(0.5417)" style="fill:none;stroke:#fff;stroke-width:2.6;stroke-linecap:round;stroke-linejoin:round">
        ${CATEGORY_ICON[r.category ?? '기타']}
      </g>
    </svg>`
  el.addEventListener('click', onClick)
  return el
}

/** 핑고 얼굴(32×32 로고)을 물방울 머리(가운데 12,10) 안에 넣는 변환. */
const MARK_IN_HEAD = 'translate(5.3 3.6) scale(0.42)'

/**
 * 올리기 전 AI 후보(#843). 요청한 사람의 AI 추천 탭에서만 화면에 그린다 — 서버의 지도는 바꾸지 않는다(가드레일 1).
 * 핑고 핀: brand-600 물방울 + 흰 테두리 + 머리에 흰 핑고 얼굴(하단 AI 탭 활성 모양과 같은 「파랑 채움 + 흰 얼굴」).
 * 카드와 같은 순위 숫자는 오른쪽 위 배지다. 「지도에 올리기」를 하면 일반 핀 모양의 핀이 된다.
 * 고른 후보는 한 번 튀어 커지고(pin-bounce) 핑고가 위에서 머리를 끌어안는다 — 몸은 MapCanvas 가 핀 뒤에, 손은 여기서 앞에 그린다.
 */
export function createCandidateMarkerElement(c: { rank: number; name: string; selected?: boolean }, onClick: () => void): HTMLElement {
  const { pin, hole, face, eyes } = PINGO_MARK
  const el = document.createElement('button')
  el.type = 'button'
  el.setAttribute('aria-label', `AI 추천 ${c.rank}위 · ${c.name}`)
  el.style.cssText =
    'position:relative;display:flex;align-items:flex-end;justify-content:center;width:44px;height:44px;padding:0;border:0;background:none;cursor:pointer;line-height:0;'
  // 손은 머리 원(가운데 12,10 · 반지름 8)의 양 어깨(위에서 ±40°)에 걸친다. 핑고(Pingo.tsx)의 흰 몸 + 외곽선과 같은 색이고,
  // 크기는 화면에서 핑고 손과 같게(그림이 1.1875배로 그려져서 그만큼 나눈 값).
  const hands = c.selected
    ? `<g class="pingo-hands" style="fill:#fff;stroke:var(--pingo-outline);stroke-width:0.84">
        <ellipse cx="6.86" cy="3.87" rx="1.52" ry="2.36" transform="rotate(-40 6.86 3.87)" />
        <ellipse cx="17.14" cy="3.87" rx="1.52" ry="2.36" transform="rotate(40 17.14 3.87)" />
      </g>`
    : ''
  // 순위 배지는 오른쪽 위다. 고르면 핑고 손이 그 자리라 커진 머리 오른쪽 옆으로 내린다.
  el.innerHTML = `
    <svg viewBox="0 0 24 32" width="30" height="38" aria-hidden="true" overflow="visible"
         style="filter:drop-shadow(0 1px 2px rgba(20,22,31,.3))"${c.selected ? ' class="pin-bounce"' : ''}>
      <path d="${PIN_PATH}" stroke-linejoin="round" style="fill:var(--brand-600);stroke:#fff;stroke-width:2" />
      <g transform="${MARK_IN_HEAD}">
        <path d="${pin}" fill="#fff" />
        <circle cx="${hole.cx}" cy="${hole.cy}" r="${hole.r}" style="fill:var(--brand-600)" />
        <rect x="${face.x}" y="${face.y}" width="${face.w}" height="${face.h}" rx="${face.rx}" fill="#fff" />
        ${eyes.map((e) => `<ellipse cx="${e.cx}" cy="${e.cy}" rx="${e.rx}" ry="${e.ry}" style="fill:var(--ink-900)" />`).join('')}
      </g>
      ${hands}
    </svg>
    <span aria-hidden="true" style="position:absolute;left:${c.selected ? 30 : 25}px;top:${c.selected ? 12 : 0}px;min-width:16px;height:16px;padding:0 3px;box-sizing:border-box;border-radius:8px;background:#fff;border:1.5px solid var(--brand-600);color:var(--brand-700);font:700 11px/13px var(--font-sans);text-align:center">${c.rank}</span>`
  el.addEventListener('click', onClick)
  return el
}

/** 고른 핀·후보를 크게(1.25배)·흰 후광·이름 말풍선으로 보인다(#308). 맨 위로 올리는 건 오버레이 쪽 일이다. */
export function markSelected(el: HTMLElement, name: string, on: boolean) {
  const svg = el.querySelector('svg')
  if (svg) {
    svg.style.transformOrigin = '50% 100%'
    svg.style.transform = on ? 'scale(1.25)' : ''
    svg.style.filter = on ? 'drop-shadow(0 0 2px #fff) drop-shadow(0 0 2px #fff)' : ''
  }
  setPinLabel(el, name, on ? 'selected' : null)
}

/**
 * 핀 아래 이름표.
 * - quiet: 지도에 찍힌 핀은 누르지 않아도 이름이 보인다. 작은 흰 알약이고 길면 말줄임한다. 겹치면 markerLayer 가 숨긴다
 * - selected: 고른 핀·후보의 말풍선(#308). 더 굵고 그림자가 진하고, 이름을 다 보인다
 * - null: 떼어 낸다(검색 결과·AI 후보는 고를 때만 이름이 있다)
 * 이름은 textContent 로만 넣는다(마크업으로 해석되지 않게). 읽는 이름은 버튼 aria-label 이 이미 갖고 있어 aria-hidden 이다.
 */
export function setPinLabel(el: HTMLElement, name: string, mode: 'quiet' | 'selected' | null) {
  el.querySelector('[data-pin-name]')?.remove()
  if (!mode || !name) return
  const label = document.createElement('span')
  label.dataset.pinName = mode
  label.textContent = name
  label.setAttribute('aria-hidden', 'true')
  label.style.cssText =
    // 그림자 대신 윤곽선 1px — 옅게 깐 바탕 지도 위에서 경계가 또렷하다. 테두리만큼 안쪽 여백을 줄여 크기는 그대로다.
    'position:absolute;top:100%;left:50%;transform:translateX(-50%);margin-top:4px;padding:1px 7px;border-radius:8px;' +
    'border:1px solid var(--ink-300);background:#fff;color:var(--ink-900);font-size:0.75rem;line-height:1.4;white-space:nowrap;pointer-events:none;' +
    (mode === 'selected' ? 'font-weight:700' : 'font-weight:600;max-width:8em;overflow:hidden;text-overflow:ellipsis')
  el.style.position = 'relative'
  el.appendChild(label)
}

/** 이름표를 겹침 정리로 숨기거나 다시 보인다. 폭을 재야 해서 display 대신 visibility 로 숨긴다. */
export function showPinLabel(el: HTMLElement, show: boolean) {
  const label = el.querySelector<HTMLElement>('[data-pin-name]')
  if (label) label.style.visibility = show ? '' : 'hidden'
}
