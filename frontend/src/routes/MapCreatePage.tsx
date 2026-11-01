import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { ChevronLeft } from 'lucide-react'

import ErrorText from '@/ErrorText'
import { createMapErrorMessage, tripReady, type TripDraft } from '@/features/maps/model'
import { useCreateMapMutation } from '@/features/maps/queries'
import TripFields from '@/features/maps/TripFields'

/**
 * 지도 만들기 (#22, Figma 1절). 제목·날짜는 필수, 지역은 선택(시·도 목록).
 * 빈 칸이 있거나 종료일이 시작일보다 앞서면 버튼이 꺼진다. 당일치기는 같은 날을 넣는다.
 */
export default function MapCreatePage() {
  const navigate = useNavigate()
  const create = useCreateMapMutation()
  const [draft, setDraft] = useState<TripDraft>({ title: '', region: null, startDate: '', endDate: '' })
  const ready = tripReady(draft)

  function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!ready) return
    create.mutate(
      { title: draft.title.trim(), start_date: draft.startDate, end_date: draft.endDate, ...(draft.region ? { region: draft.region } : {}) },
      // 방장 온보딩(Figma 3절)은 지도 화면이 이 표시를 보고 띄운다.
      { onSuccess: (map) => navigate(`/maps/${map.id}?onboarding=owner`, { replace: true }) },
    )
  }

  return (
    <form onSubmit={submit} className="mx-auto flex min-h-dvh w-full max-w-[480px] flex-col bg-ink-50 px-4 pb-6 pt-4">
      <header className="mb-6 flex items-center gap-3">
        <Link to="/" aria-label="내 지도 목록으로" className="hit-44 flex size-8 items-center justify-center rounded-full bg-white shadow-float">
          <ChevronLeft size={20} />
        </Link>
        <h1 className="text-2xl font-bold text-ink-900">새 지도</h1>
      </header>

      <TripFields value={draft} onChange={setDraft} />

      {create.error && <ErrorText message={createMapErrorMessage(create.error)} error={create.error} />}

      <button
        type="submit"
        disabled={!ready || create.isPending}
        className="btn-primary btn-lg mt-auto"
      >
        {create.isPending ? '만드는 중…' : '지도 만들기'}
      </button>
    </form>
  )
}
