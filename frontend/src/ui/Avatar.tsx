/** 구성원·내 계정 아바타. 구성원별 색이 없어서(#26) 회색 면 하나에 이름 첫 글자다. */
export default function Avatar({ name, size = 32 }: { name?: string; size?: 32 | 44 }) {
  return (
    <span
      aria-hidden="true"
      className={`flex shrink-0 items-center justify-center rounded-full bg-ink-100 font-semibold text-ink-700 ${size === 44 ? 'size-11 text-title' : 'size-8 text-sm'}`}
    >
      {name?.slice(0, 1)}
    </span>
  )
}
