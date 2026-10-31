import { useState } from 'react'
import { ChevronLeft } from 'lucide-react'

import { ApiError } from '@/api'
import ErrorText from '@/ErrorText'
import { TAB_BAR_H } from '@/features/shell/layout'
import { usePanelBack } from '@/features/shell/panelBack'
import Toaster from '@/features/shell/Toaster'
import { useIsDesktop } from '@/features/shell/useIsDesktop'
import ConfirmDialog from '@/ui/ConfirmDialog'
import Pingo from '@/ui/Pingo'
import PingoLoading from '@/ui/PingoLoading'

import { useAiStore } from './aiStore'
import EvidenceGroups from './EvidenceGroups'
import type { RecommendRunDto, RegionDto } from './model'
import { useConfirmRegionsMutation, useEvidenceQuery, useExecuteRunMutation } from './queries'

/**
 * 지역 확인 대기(awaiting_region_confirm) 전용 화면. 추천은 결과부터 보여 주고 조건은 결과 화면에서 고친다(#845) —
 * 이 화면은 사람이 쓴 반경 사유끼리 안 겹쳐 실행 전에 물어야 할 때만 남는다(5-6-1, v1에선 도달하지 않는다).
 * 조건 목록·×·＋ 는 결과 화면의 조건 카드와 같은 부품(EvidenceGroups)이다.
 */
export default function EvidenceScreen({ mapId, run }: { mapId: string; run: RecommendRunDto }) {
  const evidence = useEvidenceQuery(run.id)
  const confirm = useConfirmRegionsMutation(run.id)
  const execute = useExecuteRunMutation(mapId)
  const setRun = useAiStore((s) => s.setRun)
  const [conflict, setConflict] = useState<RegionDto[] | null>(null)
  const busy = confirm.isPending
  const desktop = useIsDesktop()
  // 넓은 화면은 이 화면 머리의 ‹ 대신 패널 헤더 ‹ 가 추천을 그만두고 AI 추천으로 돌아간다.
  usePanelBack('AI 추천', () => setRun(mapId, undefined), desktop)

  function start(acceptUnion: boolean) {
    confirm.mutate(acceptUnion, {
      onSuccess: () => {
        setConflict(null)
        execute.mutate(run)
      },
      onError: (err) => {
        // 사람이 쓴 반경 사유끼리 안 겹친다 — 사람에게 묻는다(5-6-1). 다른 실패는 그대로 보여 준다.
        if (err instanceof ApiError && err.code === 'REGION_CONFLICT') {
          setConflict((err.detail?.regions as RegionDto[] | undefined) ?? [])
        }
      },
    })
  }

  return (
    // 넓은 화면에서는 패널 안 탭 아래를 채운다 — 위쪽 헤더·탭은 그대로 보인다(#338).
    <div
      className={desktop ? 'relative flex min-h-0 flex-1 flex-col bg-white' : 'fixed inset-x-0 top-0 z-30 flex flex-col bg-white'}
      style={desktop ? undefined : { bottom: `calc(${TAB_BAR_H}px + env(safe-area-inset-bottom, 0px))` }}
    >
      <header className="flex items-center gap-2 border-b border-ink-100 px-4 py-3">
        {!desktop && (
          <button type="button" aria-label="추천 그만두기" onClick={() => setRun(mapId, undefined)} className="hit-44 text-ink-900">
            <ChevronLeft size={20} />
          </button>
        )}
        <h1 className="text-title font-bold text-ink-900">{run.category} 추천받기</h1>
      </header>

      <div className="flex-1 space-y-5 overflow-y-auto px-4 py-4">
        {/* 의견을 다 모아 조건으로 정리했다 — 핑고가 손을 든다(시안 「결정했어요!」). */}
        <div className="flex items-center gap-3 rounded-xl border border-brand-300 bg-[var(--pingo-bg)] p-4">
          <Pingo size={48} mood="wave" />
          <div className="min-w-0">
            <p className="flex items-center gap-1.5 text-sm font-bold text-[var(--pingo-text)]">
              <span className="tag tag-ai">AI</span> AI가 정리한 조건
            </p>
            <p className="mt-1 font-bold text-ink-900">이 조건으로 추천해도 될까요?</p>
            <p className="mt-1 text-xs text-ink-500">지금까지 남긴 의견을 이렇게 정리했어요.</p>
          </div>
        </div>

        {evidence.isPending && <PingoLoading label="조건을 정리하는 중…" />}
        {evidence.error && <ErrorText message="조건을 불러오지 못했어요" error={evidence.error} />}

        {evidence.data && <EvidenceGroups runId={run.id} lines={evidence.data} />}

        {confirm.error && !(confirm.error instanceof ApiError && confirm.error.code === 'REGION_CONFLICT') && (
          <ErrorText message="지역을 확인하지 못했어요" error={confirm.error} />
        )}
      </div>

      {/* 이 화면은 시트가 없어서 토스트를 아래 버튼 줄 위에 띄운다. 넓은 화면은 지도 영역 토스트 하나만 쓴다. */}
      <div className="relative grid grid-cols-2 gap-2 border-t border-ink-100 p-4">
        {!desktop && <Toaster controlsVisible={false} />}
        <button type="button" onClick={() => setRun(mapId, undefined)} className="btn-neutral btn-lg">
          취소
        </button>
        <button type="button" disabled={busy || evidence.isPending} onClick={() => start(false)} className="btn-primary btn-lg">
          {busy ? '찾기 시작하는 중…' : '네, 추천해주세요'}
        </button>
      </div>

      {conflict && (
        <ConfirmDialog
          title="두 조건을 동시에 만족하는 곳이 없어요"
          body="두 곳이 멀어서 한 번에 찾을 수 없어요. 각 지역에서 따로 찾아 결과를 나눠 보여 드릴 수 있어요."
          detail={
            conflict.length > 0 && (
              <ul className="space-y-1 font-semibold text-ink-900">
                {conflict.map((r) => (
                  <li key={r.label}>{r.label}</li>
                ))}
              </ul>
            )
          }
          note="같은 사유가 남아 있는 동안에는 다시 묻지 않아요."
          cancel="근거를 다시 볼게요"
          ok="두 지역 각각 찾기"
          onCancel={() => setConflict(null)}
          onOk={() => start(true)}
        />
      )}
    </div>
  )
}
