import Pingo from '@/ui/Pingo'

export type OnboardingKind = 'owner' | 'member'

/** 받침 있으면 첫째, 없으면 둘째 조사. 한글이 아니면 받침 없는 쪽으로 본다. */
function josa(word: string, withFinal: string, withoutFinal: string) {
  const code = word.charCodeAt(word.length - 1) - 0xac00
  return code >= 0 && code <= 11171 && code % 28 !== 0 ? withFinal : withoutFinal
}

/** v1은 지도를 길게 눌러 핀을 찍지 않는다(#191) — Figma 문구에서 그 부분만 뺐다. */
const STEPS: Record<OnboardingKind, string[]> = {
  owner: [
    '위 검색창에 가게 이름을 검색해서 핀을 찍으세요',
    '오른쪽 위 프로필에서 초대 링크로 친구를 초대하세요',
    '각자 ♥ △ 🚫로 의견을 남기면 AI가 대안을 찾아줘요',
  ],
  member: [
    '핀을 눌러 ♥ △ 🚫로 의견을 남겨주세요',
    '🚫는 이유가 필요해요. 그 이유로 대안을 찾습니다',
    '가고 싶은 곳이 있으면 위 검색창에서 추가하세요',
  ],
}

/** 온보딩(Figma 2·3절). 별도 팝업이 아니라 시트 2단계로 안내한다(최종기획안 6절). */
export function OnboardingHeader({ kind, mapTitle }: { kind: OnboardingKind; mapTitle: string }) {
  const title =
    kind === 'owner'
      ? `${mapTitle}${josa(mapTitle, '을', '를')} 만들었어요`
      : `${mapTitle}에 참여했어요`
  return (
    <div className="flex items-center gap-3 rounded-2xl bg-[var(--pingo-bg)] p-3">
      <Pingo />
      <div className="min-w-0">
        <p className="text-xs font-semibold text-[var(--pingo-text)]">핑고</p>
        <h2 className="truncate text-lg font-bold text-ink-900">{title}</h2>
        <p className="text-xs text-ink-500">{kind === 'owner' ? '이렇게 시작해 보세요' : '이렇게 함께해요'}</p>
      </div>
    </div>
  )
}

export function OnboardingBody({ kind, onDone }: { kind: OnboardingKind; onDone: () => void }) {
  return (
    <>
      <ol className="mt-2 space-y-4">
        {STEPS[kind].map((step, i) => (
          <li key={step} className="flex gap-3 text-ink-900">
            <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-brand-600 text-xs font-semibold text-white">
              {i + 1}
            </span>
            {step}
          </li>
        ))}
      </ol>
      <button type="button" onClick={onDone} className="mt-6 w-full rounded-xl bg-brand-600 py-3.5 font-semibold text-white">
        알겠어요
      </button>
    </>
  )
}
