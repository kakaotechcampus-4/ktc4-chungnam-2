/**
 * 접속 점(#1551): 지금 이 지도를 열어 둔 사람이 있다는 초록 점. 보이기만 하고 뜻은 옆 글자나 버튼 이름이 전한다.
 * 아바타 위에 얹을 때는 className 으로 자리를 준다(Avatar online).
 */
export default function OnlineDot({ className = '' }: { className?: string }) {
  return <span aria-hidden="true" data-online className={`size-2.5 shrink-0 rounded-full bg-[var(--good-line)] ring-2 ring-[var(--surface-card)] ${className}`} />
}
