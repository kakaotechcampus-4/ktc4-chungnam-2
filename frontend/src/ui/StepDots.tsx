/**
 * 여러 장 중 몇 번째인지(온보딩). 지금 장은 길쭉한 brand-600, 나머지는 ink-300 점이다.
 * 줄 맞춤은 놓이는 자리가 `className`으로 준다(기본 가운데).
 * 점은 장식이고 읽는 글은 「4장 중 2장」 하나다. 누르는 곳이 아니다 — 넘기기는 버튼·밀기가 맡는다.
 */
export default function StepDots({ count, current, className = 'justify-center' }: { count: number; current: number; className?: string }) {
  return (
    <div role="img" aria-label={`${count}장 중 ${current + 1}장`} className={`flex items-center gap-1.5 ${className}`}>
      {Array.from({ length: count }, (_, i) => (
        <span
          key={i}
          className={`h-1.5 rounded-full transition-[width] duration-200 ease-out motion-reduce:transition-none ${
            i === current ? 'w-4 bg-brand-600' : 'w-1.5 bg-ink-300'
          }`}
        />
      ))}
    </div>
  )
}
