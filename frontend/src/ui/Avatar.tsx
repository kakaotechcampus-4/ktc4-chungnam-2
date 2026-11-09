/** 구성원·내 계정 아바타. 구성원별 색이 없어서(#26) 회색 면 하나에 이름 첫 글자다. */
export default function Avatar({ name, size = 32, tone = 'ink' }: { name?: string; size?: 24 | 32 | 44; tone?: 'ink' | 'brand' }) {
  const box = size === 44 ? 'size-11 text-title' : size === 24 ? 'size-6 text-label' : 'size-8 text-sm'
  // brand 는 여러 사람을 겹쳐 보이는 자리(PeopleProof)용 — 사람마다 색을 나누지는 않는다(#26).
  const color = tone === 'brand' ? 'bg-[var(--selected-bg)] text-[var(--selected-text)]' : 'bg-ink-100 text-ink-700'
  return (
    <span aria-hidden="true" className={`flex shrink-0 items-center justify-center rounded-full font-semibold ${box} ${color}`}>
      {name && Array.from(name)[0]}
    </span>
  )
}
