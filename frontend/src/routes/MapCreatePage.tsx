import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router'
import type { components } from '@pingo/contracts/src/types/api'

import { api, ApiError } from '@/api'

type MapInfo = components['schemas']['Map']
type MapCreateRequest = components['schemas']['MapCreateRequest']

/**
 * 지도 생성 폼 (#22) — 여행 제목 + 시작일·종료일.
 * 지역 검색(필수 아님)은 스펙 반영(#136) 뒤에 붙인다.
 */
export default function MapCreatePage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [startDate, setStartDate] = useState('')

  const create = useMutation({
    mutationFn: (body: MapCreateRequest) =>
      api<MapInfo>('/maps', { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: (map) => {
      void queryClient.invalidateQueries({ queryKey: ['maps'] })
      navigate(`/maps/${map.id}`, { replace: true })
    },
  })

  function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    create.mutate({
      title: String(form.get('title')).trim(),
      start_date: String(form.get('start_date')),
      end_date: String(form.get('end_date')),
    })
  }

  return (
    <form onSubmit={submit} className="space-y-4 p-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">새 지도</h1>
        <Link to="/" className="text-sm text-muted-foreground">
          취소
        </Link>
      </div>

      <label className="block space-y-1">
        <span className="text-sm">여행 제목</span>
        <input
          name="title"
          required
          maxLength={100}
          placeholder="예: 부산 1박 2일"
          className="w-full rounded-md border px-3 py-2 text-sm"
        />
      </label>

      <div className="grid grid-cols-2 gap-2">
        <label className="block space-y-1">
          <span className="text-sm">시작일</span>
          <input
            type="date"
            name="start_date"
            required
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="w-full rounded-md border px-3 py-2 text-sm"
          />
        </label>
        <label className="block space-y-1">
          <span className="text-sm">종료일</span>
          {/* 종료일은 시작일 이후여야 한다(스펙 MapCreateRequest.end_date). 브라우저가 막는다. */}
          <input
            type="date"
            name="end_date"
            required
            min={startDate || undefined}
            className="w-full rounded-md border px-3 py-2 text-sm"
          />
        </label>
      </div>

      {create.error && (
        <p className="text-sm text-destructive">
          지도를 만들지 못했어요
          {create.error instanceof ApiError && (
            <span className="ml-1 font-mono text-xs">({create.error.code})</span>
          )}
        </p>
      )}

      <button
        type="submit"
        disabled={create.isPending}
        className="w-full rounded-md bg-primary py-2 text-sm text-primary-foreground disabled:opacity-50"
      >
        {create.isPending ? '만드는 중…' : '지도 만들기'}
      </button>
    </form>
  )
}
