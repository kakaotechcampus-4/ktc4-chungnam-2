import { Switch as RadixSwitch } from 'radix-ui'

/**
 * 켜고 끄기(모드 스위치). 보이는 막대는 44×24, 누르는 곳은 44×44다. 켜짐은 brand-600 채움, 꺼짐은 ink-300 —
 * 색만으로 전하지 않게 스크린리더는 role=switch 의 켜짐 상태를 읽고, 화면은 옆 글자가 상태를 말한다.
 */
export default function Switch({ checked, onChange, label, disabled }: { checked: boolean; onChange: (on: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <RadixSwitch.Root
      checked={checked}
      onCheckedChange={onChange}
      disabled={disabled}
      aria-label={label}
      className="hit-44 relative inline-flex h-6 w-11 shrink-0 items-center rounded-full bg-ink-300 transition-colors duration-200 ease-out data-[state=checked]:bg-brand-600 disabled:opacity-50 motion-reduce:transition-none"
    >
      <RadixSwitch.Thumb className="block size-5 translate-x-0.5 rounded-full bg-white transition-transform duration-200 ease-out data-[state=checked]:translate-x-[22px] motion-reduce:transition-none" />
    </RadixSwitch.Root>
  )
}
