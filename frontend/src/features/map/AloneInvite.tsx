import ErrorText from '@/ErrorText'
import { useShareInvite } from '@/features/maps/useShareInvite'
import Pingo from '@/ui/Pingo'
import Sentences from '@/ui/Sentences'

import { INVITE_BUTTON } from './Onboarding'

/**
 * 핀은 있는데 구성원이 나 하나일 때 마킹 탭 목록 위에 두는 초대 안내(기획안 6절 「함께 만든 화면」, #1560).
 * 지도를 만든 직후 온보딩이 한 번 권한 뒤에도 혼자 핀만 쌓이는 때를 위한 자리다. 둘 이상이 되면 MapTab 이 그리지 않는다.
 * 링크는 그릴 때 만든다 — 서버는 내 유효한 링크를 다시 쓴다(useShareInvite, #467).
 */
export default function AloneInvite({ mapId }: { mapId: string }) {
  const { share, status, error, retry } = useShareInvite(mapId)
  return (
    <section aria-label="친구 초대 안내" className="flex items-start gap-3 rounded-xl bg-[var(--pingo-bg)] p-3">
      <Pingo size={40} mood="welcome" />
      <div className="min-w-0 flex-1 space-y-2">
        <div>
          <p className="text-sm font-bold text-ink-900">아직 나 혼자예요</p>
          <p className="text-body text-ink-700">
            <Sentences text="친구를 초대하면 핀마다 의견을 모아 함께 정할 수 있어요" />
          </p>
        </div>
        <button
          type="button"
          onClick={status === 'failed' ? retry : () => void share()}
          disabled={status === 'creating'}
          className="btn-outline btn-sm"
        >
          {INVITE_BUTTON[status]}
        </button>
        {status === 'failed' && <ErrorText message="초대 링크를 만들지 못했어요" error={error} />}
      </div>
    </section>
  )
}
