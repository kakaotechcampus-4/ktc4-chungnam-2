import type { ReactNode } from 'react'

import { useShareInvite } from '@/features/maps/useShareInvite'
import AgainstMark from '@/ui/AgainstMark'
import { josa } from '@/ui/josa'
import Pingo from '@/ui/Pingo'

export type OnboardingKind = 'owner' | 'member'

/** v1은 지도를 길게 눌러 핀을 찍지 않는다(#191) — Figma 문구에서 그 부분만 뺐다. */
const STEPS: Record<OnboardingKind, ReactNode[]> = {
  owner: [
    '위 검색창에 가게 이름을 검색해서 핀을 찍으세요',
    '친구를 초대하세요. 나중에도 오른쪽 위 구성원 버튼에서 초대할 수 있어요',
    <>각자 ♥ <AgainstMark />로 의견을 남기면 AI가 대안을 찾아줘요</>,
  ],
  member: [
    <>핀을 눌러 ♥ <AgainstMark />로 의견을 남겨주세요</>,
    <><AgainstMark /> 반대는 이유가 필요해요. 그 이유로 대안을 찾아요</>,
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

export function OnboardingBody({ mapId, kind, onDone }: { mapId: string; kind: OnboardingKind; onDone: () => void }) {
  return (
    <>
      <ol className="mt-2 space-y-4">
        {STEPS[kind].map((step, i) => (
          <li key={i} className="flex gap-3 text-ink-900">
            <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-brand-50 text-xs font-semibold text-brand-600">
              {i + 1}
            </span>
            <span className="break-keep">{step}</span>
          </li>
        ))}
      </ol>
      {kind === 'owner' ? (
        <OwnerActions mapId={mapId} onDone={onDone} />
      ) : (
        <button type="button" onClick={onDone} className="btn-primary mt-6 w-full py-3.5">
          알겠어요
        </button>
      )}
    </>
  )
}

/**
 * 지도를 막 만든 방장의 다음 할 일은 초대다. 문장으로만 안내하지 않고 이 화면의 유일한 채움 버튼으로 둔다(#351).
 * 공유 창이 없는 브라우저는 링크 복사로 대신한다.
 */
function OwnerActions({ mapId, onDone }: { mapId: string; onDone: () => void }) {
  const { share, url } = useShareInvite(mapId)
  return (
    <div className="mt-6 space-y-1">
      <button
        type="button"
        onClick={() => void share()}
        disabled={!url}
        className="btn-primary w-full py-3.5"
      >
        {url ? '친구 초대하기' : '초대 링크를 만드는 중…'}
      </button>
      <button type="button" onClick={onDone} className="w-full py-3 text-sm font-semibold text-ink-600">
        나중에 할게요
      </button>
    </div>
  )
}
