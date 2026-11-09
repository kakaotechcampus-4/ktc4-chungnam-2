import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import { useSheetStore } from '@/features/shell/sheetStore'

import Pingo from './Pingo'

const SEEN_PREFIX = 'coach.'
/** 화면이 자리를 잡은 뒤에 짚는다 — 탭을 바꾸자마자 뜨면 시트가 올라오는 중이라 자리가 어긋났다. */
const SHOW_AFTER_MS = 700
/** 짚는 자리 둘레 여백과 말풍선과의 간격. */
const PAD = 6
const GAP = 12
const BUBBLE_MAX = 320
const EDGE = 16

/** 지금 떠 있는 코치마크 — 한 번에 하나만. 둘이 같이 열리면 먼저 연 것만 뜬다. */
let showing: string | null = null

function seen(id: string): boolean {
  try {
    return localStorage.getItem(SEEN_PREFIX + id) === '1'
  } catch {
    return true // 기억할 수 없으면 탭에 올 때마다 다시 뜨니 띄우지 않는다
  }
}

function markSeen(id: string) {
  try {
    localStorage.setItem(SEEN_PREFIX + id, '1')
  } catch {
    // 저장이 막혀도 이번에는 닫는다
  }
}

/**
 * 짚을 자리 — `data-coach` 가 같은 요소에서 지금 보이는 부분. 시트 안 목록처럼 스크롤 칸에 잘린 요소는 잘린 만큼만 짚는다
 * (휴대폰 절반 시트에서 칸이 탭 막대 밑까지 밝게 짚혔다). 보이는 부분이 없으면(숨김·테스트 환경) 없는 것으로 본다.
 */
function findTarget(target: string): DOMRect | null {
  const el = document.querySelector(`[data-coach="${target}"]`)
  if (!el) return null
  const r = el.getBoundingClientRect()
  let [left, top, right, bottom] = [r.left, r.top, r.right, r.bottom]
  for (let p = el.parentElement; p; p = p.parentElement) {
    if (!/(auto|scroll|hidden)/.test(getComputedStyle(p).overflowY)) continue
    const c = p.getBoundingClientRect()
    ;[left, top, right, bottom] = [Math.max(left, c.left), Math.max(top, c.top), Math.min(right, c.right), Math.min(bottom, c.bottom)]
  }
  ;[left, top, right, bottom] = [Math.max(left, 0), Math.max(top, 0), Math.min(right, window.innerWidth), Math.min(bottom, window.innerHeight)]
  return right - left > 0 && bottom - top > 0 ? new DOMRect(left, top, right - left, bottom - top) : null
}

/**
 * 코치마크(#1658) — 처음 쓰는 사람에게 버튼 자리를 한 번 짚어 준다. 짚을 자리(`data-coach="{target}"`)만 밝게 두고 나머지를 `--scrim`으로 덮은 뒤,
 * 옆에 핑고 말풍선(제목 + 한 줄 + 「알겠어요」)을 띄운다. 아래 자리가 모자라면 위에 띄운다.
 * - 한 번 닫으면 이 기기에서 다시 뜨지 않는다(localStorage `coach.{id}`, 서버에는 남기지 않는다).
 * - 덮개는 누름을 막지 않는다 — 아무 곳이나 누르면 닫히고 그 누름은 그대로 아래로 간다. Esc로도 닫힌다.
 * - 짚을 자리가 없거나 모달이 열려 있으면 띄우지 않고, 본 것으로도 치지 않는다(다음에 자리가 있을 때 뜬다).
 * - 자동화 브라우저(`navigator.webdriver`, e2e)에서는 띄우지 않는다 — 말풍선이 시나리오가 누를 버튼을 가린다.
 */
export default function CoachMark({ id, target, title, children }: { id: string; target: string; title: string; children: string }) {
  const modalOpen = useSheetStore((s) => s.modalOpen)
  const [rect, setRect] = useState<DOMRect | null>(null)
  const [open, setOpen] = useState(false)
  const bubble = useRef<HTMLDivElement>(null)
  const [bubbleH, setBubbleH] = useState(0)
  const titleId = useId()

  // 띄울지 정한다 — 잠깐 기다렸다가 자리가 있으면 연다.
  useEffect(() => {
    if (open || modalOpen || navigator.webdriver || seen(id) || (showing && showing !== id)) return
    const t = setTimeout(() => {
      if (showing || !findTarget(target)) return
      showing = id
      setRect(findTarget(target))
      setOpen(true)
    }, SHOW_AFTER_MS)
    return () => clearTimeout(t)
  }, [id, target, open, modalOpen])

  // 떠 있는 동안 자리를 따라간다(시트가 오르내리거나 목록이 스크롤될 때). 자리가 사라지면 닫는다.
  useEffect(() => {
    if (!open) return
    let frame = 0
    const follow = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => setRect(findTarget(target)))
    }
    window.addEventListener('resize', follow)
    window.addEventListener('scroll', follow, true)
    const timer = setInterval(follow, 300) // 시트 높이 바뀜은 이벤트가 없다
    return () => {
      cancelAnimationFrame(frame)
      clearInterval(timer)
      window.removeEventListener('resize', follow)
      window.removeEventListener('scroll', follow, true)
    }
  }, [open, target])

  const close = () => {
    markSeen(id)
    showing = null
    setOpen(false)
  }

  // 아무 곳이나 누르거나 Esc — 말풍선 안의 누름은 「알겠어요」가 받는다.
  useEffect(() => {
    if (!open) return
    const onDown = (e: PointerEvent) => {
      if (!bubble.current?.contains(e.target as Node)) close()
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    document.addEventListener('pointerdown', onDown, true)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onDown, true)
      document.removeEventListener('keydown', onKey)
    }
  })

  // 모달이 열리면 말풍선이 모달 위에 남지 않게 닫는다. 화면을 떠나면(언마운트) 다음 코치마크가 뜰 수 있게 비운다.
  useEffect(() => {
    if (open && modalOpen) close()
  })
  useEffect(() => () => {
    if (showing === id) showing = null
  }, [id])

  useLayoutEffect(() => {
    if (open && bubble.current) setBubbleH(bubble.current.offsetHeight)
  }, [open, rect])

  if (!open || !rect) return null

  const width = Math.min(BUBBLE_MAX, window.innerWidth - EDGE * 2)
  const below = rect.bottom + PAD + GAP + bubbleH <= window.innerHeight - EDGE || rect.top - PAD - GAP - bubbleH < EDGE
  const top = below ? rect.bottom + PAD + GAP : rect.top - PAD - GAP - bubbleH
  const left = Math.min(Math.max(rect.left + rect.width / 2 - width / 2, EDGE), window.innerWidth - width - EDGE)
  // 꼬리는 짚은 자리 가운데를 가리킨다(말풍선 모서리 둥근 곳은 피한다).
  const tail = Math.min(Math.max(rect.left + rect.width / 2 - left, 20), width - 20)

  return createPortal(
    <>
      <div
        aria-hidden="true"
        className="coach-spot pointer-events-none fixed z-[55] rounded-xl"
        style={{ left: rect.left - PAD, top: rect.top - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2 }}
      />
      <div
        ref={bubble}
        role="status"
        aria-labelledby={titleId}
        className="enter-pop fixed z-[56] rounded-xl bg-surface p-3.5 shadow-float"
        style={{ left, top, width }}
      >
        <span
          aria-hidden="true"
          className={`absolute size-3 rotate-45 bg-surface ${below ? '-top-1.5' : '-bottom-1.5'}`}
          style={{ left: tail - 6 }}
        />
        <div className="flex items-start gap-2.5">
          <Pingo size={40} mood="welcome" />
          <div className="min-w-0 flex-1">
            <p id={titleId} className="break-keep text-sm font-bold text-ink-900">
              {title}
            </p>
            <p className="mt-0.5 break-keep text-body text-ink-700">{children}</p>
          </div>
        </div>
        <div className="mt-2.5 flex justify-end">
          {/* 포커스를 옮기지 않는다 — 짚은 버튼을 바로 누를 수 있게 둔다. 화면 읽기는 status 로 읽는다.
              채움 버튼은 짚은 버튼 하나다(한 화면 한 채움 규칙). */}
          <button type="button" onClick={close} className="btn-outline btn-sm">
            알겠어요
          </button>
        </div>
      </div>
    </>,
    document.body,
  )
}
