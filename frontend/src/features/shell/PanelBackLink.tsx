import BackButton from '@/ui/BackButton'

import { usePanelBack } from './panelBack'
import { useIsDesktop } from './useIsDesktop'

/**
 * 시트·패널 안 이전 화면으로 가는 「‹ 마킹된 장소」. 모바일은 그 자리에 BackButton 으로 그리고,
 * 넓은 화면은 패널 헤더 ‹ 로 옮겨 간다 — 한 패널에 ‹ 가 두 개 겹치지 않게.
 */
export default function PanelBackLink({ label, onBack }: { label: string; onBack: () => void }) {
  const desktop = useIsDesktop()
  usePanelBack(label, onBack, desktop)
  if (desktop) return null
  return <BackButton label={label} onClick={onBack} />
}
