const COLORS = ['var(--brand-600)', 'var(--brand-300)', 'var(--pin-confirmed)', 'var(--good-line)']
const PIECES = 28
/** 떨어지는 1.5초 + 가장 늦게 출발하는 조각 0.3초 뒤에 지운다. */
const REMOVE_AFTER_MS = 1900

/**
 * 컨페티를 한 번 뿌린다(#1723, 완료 표시 컨페티). React 밖에서 그렸다가 스스로 지운다 — 뿌리는 중에 탭을 옮겨도 끊기지 않고, 돌아와도 다시 뿌리지 않는다.
 * 뜻은 화면의 글이 전하므로 화면 읽기에는 숨긴다. 동작 줄이기면 뿌리지 않는다. 조각 자리는 번호로 정해 매번 같다.
 */
export function fireConfetti() {
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
  const box = document.createElement('div')
  box.className = 'confetti'
  box.setAttribute('aria-hidden', 'true')
  for (let i = 0; i < PIECES; i++) {
    const piece = document.createElement('i')
    piece.style.cssText = `left:${(i * 37) % 100}%;background:${COLORS[i % COLORS.length]};--drift:${((i * 53) % 120) - 60}px;--spin:${(i * 97) % 720}deg;animation-delay:${(i * 29) % 300}ms`
    box.append(piece)
  }
  document.body.append(box)
  setTimeout(() => box.remove(), REMOVE_AFTER_MS)
}
