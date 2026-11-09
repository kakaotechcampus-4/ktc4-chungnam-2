import OnlineDot from './OnlineDot'

/**
 * 구성원·내 계정 아바타. 구성원별 색이 없어서(#26) 회색 면 하나에 이름 첫 글자다.
 * online 이면 오른쪽 아래에 초록 접속 점을 단다(#1551). 점은 보이기만 하고 뜻은 옆 글자나 버튼 이름이 전한다.
 */
export default function Avatar({ name, size = 32, online = false }: { name?: string; size?: 24 | 32 | 44; online?: boolean }) {
  const box = size === 44 ? 'size-11 text-title' : size === 24 ? 'size-6 text-label' : 'size-8 text-sm'
  return (
    <span aria-hidden="true" className={`relative flex shrink-0 items-center justify-center rounded-full font-semibold ${box} bg-ink-100 text-ink-700`}>
      {name && Array.from(name)[0]}
      {online && <OnlineDot className="absolute -bottom-0.5 -right-0.5" />}
    </span>
  )
}
