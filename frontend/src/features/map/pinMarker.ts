import type { PlaceSearchResultDto } from '@/features/search/model'
import { categoryIconPath } from '@/ui/CategoryIcon'
import { pinGlyph } from '@/ui/pinGlyph'

import { kindLabel, type Pin } from './model'


/** 새 소식 점 — 핀 머리 오른쪽 위(#1454). */
const FRESH_DOT =
  '<span data-new-dot aria-hidden="true" style="position:absolute;left:28px;top:3px;width:10px;height:10px;border-radius:9999px;background:var(--brand-600);border:2px solid #fff"></span>'

/**
 * 지도 위 핀 — 일반(올린 AI 추천 포함)·확정. 핀 그림은 `ui/pinGlyph` 한 곳에서 만든다(색의 진하기는 참여율, 구성원별 색 구분은 없다 #26).
 * fresh: 마지막으로 본 뒤 새로 생긴 핀·의견이 있는 핀(#1454) — 머리 오른쪽 위에 파란 점을 단다(목록 「새 핀」 태그와 같은 브랜드 파랑).
 */
export function createPinMarkerElement(pin: Pin, ratio: number, onClick: () => void, fresh = false): HTMLElement {
  const el = document.createElement('button')
  el.type = 'button'
  // 장소 이름은 setAttribute 로만 넣는다 — innerHTML 로 들어가면 이름이 마크업으로 해석된다.
  el.setAttribute('aria-label', `${pin.place_name ?? '이름 없는 핀'}, ${kindLabel(pin.kind)} 핀${fresh ? ', 새 소식 있음' : ''}`)
  el.dataset.pinTone = pin.kind === '확정' ? 'confirmed' : 'normal'
  el.style.cssText =
    'position:relative;display:flex;align-items:flex-end;justify-content:center;width:44px;height:44px;padding:0;border:0;background:none;cursor:pointer;line-height:0;'
  el.innerHTML = `
    <svg viewBox="0 0 24 32" width="30" height="38" aria-hidden="true">
      ${pinGlyph(pin.kind === '확정' ? { kind: 'confirmed' } : { kind: 'normal', ratio })}
    </svg>${
      fresh
        ? FRESH_DOT
        : ''
    }`
  el.addEventListener('click', onClick)
  return el
}

/**
 * 화면에서 겹친 지도 핀 여러 곳(#1576). 핀 모양 그대로 머리에 곳 수를 적는다(`pinGlyph` count).
 * 모두 확정이면 확정 핀 색, 하나라도 아니면 일반 핀 색이고 진하기는 묶음 안에서 가장 높은 참여율이다.
 * 새 소식이 있는 핀이 하나라도 있으면 파란 점을 단다. 누르면 확대해 풀거나, 더 확대해도 겹치면 그 핀들 목록을 연다(MapCanvas).
 * 이름은 setAttribute 로만 넣는다(마크업으로 해석되지 않게).
 */
export function createPinGroupMarkerElement(
  g: { names: string[]; confirmed: boolean; ratio: number; fresh: boolean },
  onClick: () => void,
): HTMLElement {
  const el = document.createElement('button')
  el.type = 'button'
  el.setAttribute('aria-label', `핀 ${g.names.length}곳이 겹쳐 있어요 · ${g.names.join(', ')}${g.fresh ? ', 새 소식 있음' : ''}`)
  el.style.cssText =
    'position:relative;display:flex;align-items:flex-end;justify-content:center;width:44px;height:44px;padding:0;border:0;background:none;cursor:pointer;line-height:0;'
  const count = g.names.length
  el.innerHTML = `
    <svg viewBox="0 0 24 32" width="30" height="38" aria-hidden="true">
      ${pinGlyph(g.confirmed ? { kind: 'confirmed', count } : { kind: 'normal', ratio: g.ratio, count })}
    </svg>${g.fresh ? FRESH_DOT : ''}`
  el.addEventListener('click', onClick)
  return el
}

type SearchCategory = NonNullable<PlaceSearchResultDto['category']>

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
  el.setAttribute('aria-label', [`검색 결과 ${r.n}번`, r.name, r.category].filter(Boolean).join(', '))
  el.dataset.pinTone = 'search'
  if (r.selected) el.setAttribute('aria-current', 'true')
  el.style.cssText =
    'display:flex;align-items:flex-end;justify-content:center;width:44px;height:44px;padding:0;border:0;background:none;cursor:pointer;line-height:0;'
  el.innerHTML = `
    <svg viewBox="0 0 32 38" width="32" height="38" aria-hidden="true"
         style="filter:drop-shadow(0 1px 2px rgba(20,22,31,.3))"${r.selected ? ' class="pin-bounce"' : ''}>
      <path d="M11 26L16 36.5L21 26Z" stroke-linejoin="round" style="fill:var(--pin-stroke);stroke:#fff;stroke-width:2" />
      <circle cx="16" cy="16" r="14" style="fill:var(--pin-stroke);stroke:#fff;stroke-width:2" />
      <g transform="translate(9.5 9.5) scale(0.5417)" style="fill:none;stroke:#fff;stroke-width:2.6;stroke-linecap:round;stroke-linejoin:round">
        ${categoryIconPath(r.category)}
      </g>
    </svg>`
  el.addEventListener('click', onClick)
  return el
}

/**
 * 화면에서 겹친 검색 결과 여러 곳(#1174). 검색 핀과 같은 빨간 원에 아이콘 대신 곳 수(숫자만, 두 자리까지 원 안에 든다)를 적는다.
 * 뒤에 원을 비껴 깔던 겹침 표시는 뺐다 — 숫자가 이미 여러 곳이라고 말해서 군더더기였다(#1576). 누르면 시트에 그곳들만 보인다.
 * 카카오맵은 20m 축척보다 더 확대하지 못해서, 같은 건물 가게들은 확대로 떼어 낼 수 없다.
 * 이름은 setAttribute 로만 넣는다(마크업으로 해석되지 않게).
 */
export function createSearchGroupMarkerElement(names: string[], onClick: () => void): HTMLElement {
  const el = document.createElement('button')
  el.type = 'button'
  el.setAttribute('aria-label', `검색 결과 ${names.length}곳이 모여 있어요 · ${names.join(', ')}`)
  el.style.cssText =
    'display:flex;align-items:flex-end;justify-content:center;width:44px;height:44px;padding:0;border:0;background:none;cursor:pointer;line-height:0;'
  el.innerHTML = `
    <svg viewBox="0 0 32 38" width="32" height="38" aria-hidden="true"
         style="filter:drop-shadow(0 1px 2px rgba(20,22,31,.3))">
      <path d="M11 26L16 36.5L21 26Z" stroke-linejoin="round" style="fill:var(--pin-stroke);stroke:#fff;stroke-width:2" />
      <circle cx="16" cy="16" r="14" style="fill:var(--pin-stroke);stroke:#fff;stroke-width:2" />
      <text x="16" y="16" text-anchor="middle" dominant-baseline="central"
            style="fill:#fff;font:700 13px var(--font-sans)">${names.length}</text>
    </svg>`
  el.addEventListener('click', onClick)
  return el
}

/**
 * 올리기 전 AI 후보(#843). 요청한 사람의 AI 추천 탭에서만 화면에 그린다 — 서버의 지도는 바꾸지 않는다(가드레일 1).
 * 핑고 핀(그림은 `ui/pinGlyph`의 candidate).
 * 카드와 같은 순위 숫자는 오른쪽 위 배지다. 「지도에 올리기」를 하면 일반 핀 모양의 핀이 된다.
 * 고른 후보는 한 번 튀어 커지고(pin-bounce) 핑고가 위에서 머리를 끌어안는다 — 몸은 MapCanvas 가 핀 뒤에, 손은 여기서 앞에 그린다.
 */
export function createCandidateMarkerElement(c: { rank: number; name: string; selected?: boolean }, onClick: () => void): HTMLElement {
  const el = document.createElement('button')
  el.type = 'button'
  el.setAttribute('aria-label', `AI 추천 ${c.rank}위, ${c.name}`)
  el.dataset.pinTone = 'candidate'
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
    <svg viewBox="0 0 24 32" width="30" height="38" aria-hidden="true" overflow="visible"${c.selected ? ' class="pin-bounce"' : ''}>
      ${pinGlyph({ kind: 'candidate' })}
      ${hands}
    </svg>
    <span aria-hidden="true" style="position:absolute;left:${c.selected ? 30 : 25}px;top:${c.selected ? 12 : 0}px;min-width:16px;height:16px;padding:0 3px;box-sizing:border-box;border-radius:8px;background:#fff;border:1.5px solid var(--brand-600);color:var(--brand-700);font:700 11px/13px var(--font-sans);text-align:center">${c.rank}</span>`
  el.addEventListener('click', onClick)
  return el
}

/**
 * 지도 자리 메뉴(#1549) — 항목은 「신규 핀 찍기」 하나다. 부르는 법만 넷이다(왼쪽 클릭·짧게 누르기·길게 누르기는 말풍선, PC 우클릭은 메뉴).
 * - `bubble`: 누른 자리 위 말풍선(#1028). 아래 작은 점이 누른 자리다(오버레이 yAnchor 1 → 점 가운데가 좌표).
 * - `menu`: 커서 자리의 작은 메뉴(오버레이 xAnchor·yAnchor 0 → 왼쪽 위가 좌표). 키보드로 고를 수 있게 열리면 항목에 포커스를 둔다.
 * 버튼은 btn-outline btn-sm 부품이다.
 */
export function createTapBubbleElement(onPress: () => void, style: 'bubble' | 'menu' = 'bubble'): HTMLElement {
  const button = document.createElement('button')
  button.type = 'button'
  button.className = 'btn-outline btn-sm shadow-float'
  button.textContent = '신규 핀 찍기'
  button.addEventListener('click', onPress)
  const box = document.createElement('div')
  box.className = 'enter-pop'
  if (style === 'menu') {
    box.setAttribute('role', 'menu')
    box.setAttribute('aria-label', '지도 메뉴')
    box.style.cssText = 'transform-origin:0 0;margin:4px 0 0 4px'
    button.setAttribute('role', 'menuitem')
    box.append(button)
    return box
  }
  box.style.cssText = 'display:flex;flex-direction:column;align-items:center;gap:6px;transform-origin:50% 100%'
  const dot = document.createElement('span')
  dot.setAttribute('aria-hidden', 'true')
  dot.style.cssText =
    'width:12px;height:12px;margin-bottom:-6px;border-radius:9999px;background:var(--brand-600);border:2px solid #fff;box-shadow:0 1px 3px rgba(20,22,31,.3)'
  box.append(button, dot)
  return box
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

type PinTone = 'normal' | 'confirmed' | 'candidate' | 'search'

/** 이름표 색 — 핀의 윤곽선 색(line)으로 테두리·글자를, 고르면 핀의 채움 색(fill)으로 채우고 그 위 글자(on). */
const LABEL_TONE: Record<PinTone, { line: string; fill: string; on: string }> = {
  normal: { line: 'var(--pin-outline)', fill: 'var(--pin-outline)', on: '#fff' },
  confirmed: { line: 'var(--pin-confirmed-mark)', fill: 'var(--pin-confirmed)', on: 'var(--pin-confirmed-mark)' },
  candidate: { line: 'var(--brand-700)', fill: 'var(--brand-500)', on: '#fff' },
  search: { line: 'var(--pin-stroke)', fill: 'var(--pin-stroke)', on: '#fff' },
}

/** 이름표 자리(px) — 핀 끝에서 띄우는 거리(꼬리 높이 포함)와 높이. 겹침 정리(markerLayer)도 이 값으로 잰다. */
export const PIN_LABEL = { gap: 6, h: 21 }

/**
 * 핀 아래 이름표 — 핀 색 말풍선(2026-11-09). 흰 바탕 + 핀 윤곽선 색 테두리·글자이고, 위로 난 꼬리가 핀 끝을 가리킨다.
 * 회색 테두리 흰 알약일 땐 핀과도 바탕 지도와도 이어지지 않아 따로 뜬 상자로 보였다. 색은 핀 종류(`data-pin-tone`)를 따른다.
 * - quiet: 지도에 찍힌 핀은 누르지 않아도 이름이 보인다. 길면 말줄임한다. 겹치면 markerLayer 가 숨긴다
 * - selected: 고른 핀·후보·검색 결과(#308). 핀 색으로 채워 어느 것을 골랐는지 보이고, 이름을 다 보인다
 * - null: 떼어 낸다(검색 결과·AI 후보는 고를 때만 이름이 있다)
 * 꼬리는 바깥 틀에, 말줄임은 안쪽 글자에 둔다 — 한 겹이면 말줄임의 overflow:hidden 이 꼬리를 잘랐다.
 * 이름은 textContent 로만 넣는다(마크업으로 해석되지 않게). 읽는 이름은 버튼 aria-label 이 이미 갖고 있어 aria-hidden 이다.
 */
export function setPinLabel(el: HTMLElement, name: string, mode: 'quiet' | 'selected' | null) {
  el.querySelector('[data-pin-name]')?.remove()
  if (!mode || !name) return
  const tone = LABEL_TONE[(el.dataset.pinTone as PinTone | undefined) ?? 'normal']
  const filled = mode === 'selected'
  const bg = filled ? tone.fill : 'var(--surface-card)' // 다크에서는 카드 면(#1412)
  const label = document.createElement('span')
  label.dataset.pinName = mode
  label.setAttribute('aria-hidden', 'true')
  label.style.cssText =
    `position:absolute;top:100%;left:50%;transform:translateX(-50%);margin-top:${PIN_LABEL.gap}px;padding:1px 7px;border-radius:6px;` +
    `border:1px solid ${tone.line};background:${bg};color:${filled ? tone.on : tone.line};` +
    'font-size:0.75rem;font-weight:700;line-height:1.4;white-space:nowrap;pointer-events:none;'
  const tail = document.createElement('span')
  tail.style.cssText =
    `position:absolute;left:50%;top:-4px;width:7px;height:7px;transform:translateX(-50%) rotate(45deg);` +
    `background:${bg};border-left:1px solid ${tone.line};border-top:1px solid ${tone.line}`
  const text = document.createElement('span')
  text.textContent = name
  text.style.cssText = filled ? 'position:relative;display:block' : 'position:relative;display:block;max-width:8em;overflow:hidden;text-overflow:ellipsis'
  label.append(tail, text)
  el.style.position = 'relative'
  el.appendChild(label)
}

/** 이름표를 겹침 정리로 숨기거나 다시 보인다. 폭을 재야 해서 display 대신 visibility 로 숨긴다. */
export function showPinLabel(el: HTMLElement, show: boolean) {
  const label = el.querySelector<HTMLElement>('[data-pin-name]')
  if (label) label.style.visibility = show ? '' : 'hidden'
}
