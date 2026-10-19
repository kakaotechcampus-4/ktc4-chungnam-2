import { DropdownMenu } from 'radix-ui'
import { Check, ChevronDown, LayoutGrid, Plus } from 'lucide-react'
import { useNavigate } from 'react-router'

import ErrorText from '@/ErrorText'

import { useMapsQuery } from './queries'

const ITEM = 'flex min-h-11 cursor-pointer items-center gap-2 rounded-lg px-2.5 text-sm outline-none data-[highlighted]:bg-ink-100'

/**
 * 넓은 화면 패널 헤더의 지도 제목 = 지도 바꾸기 메뉴. 내 지도 목록은 처음 지도를 고를 때만 거치고,
 * 그 뒤로는 여기서 바로 다른 지도로 옮긴다. 헤더 ‹ 는 패널 안 이전 화면 전용이라 지도 밖으로 나가는 길은 이 메뉴뿐이다.
 * 모바일은 지도 위에 제목이 없어서 좌상단 ‹(내 지도 목록)를 그대로 쓴다.
 */
export default function MapSwitcher({ mapId, title }: { mapId: string; title?: string }) {
  const navigate = useNavigate()
  const maps = useMapsQuery()

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger
        aria-label={title ? `${title} · 다른 지도로 바꾸기` : '다른 지도로 바꾸기'}
        className="group -ml-1.5 flex h-9 min-w-0 flex-1 items-center gap-1 rounded-lg px-1.5 text-left outline-none hover:bg-ink-100 focus-visible:outline-2 focus-visible:outline-[var(--line-focus)] data-[state=open]:bg-ink-100"
      >
        <span className="truncate text-[1.0625rem] font-bold text-ink-900">{title}</span>
        <ChevronDown size={16} aria-hidden="true" className="shrink-0 text-ink-500 transition-transform group-data-[state=open]:rotate-180 motion-reduce:transition-none" />
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="start"
          sideOffset={6}
          className="z-50 max-h-[min(480px,var(--radix-dropdown-menu-content-available-height))] w-[var(--radix-dropdown-menu-trigger-width)] min-w-64 overflow-y-auto rounded-xl border border-ink-200 bg-white p-1.5 shadow-md"
        >
          <DropdownMenu.Label className="px-2.5 pb-1 pt-1.5 text-xs text-ink-500">내 지도</DropdownMenu.Label>
          {maps.isPending && <p className="px-2.5 py-2 text-sm text-ink-500">불러오는 중…</p>}
          {maps.error && (
            <div className="px-2.5 py-2">
              <ErrorText message="지도 목록을 불러오지 못했어요" error={maps.error} />
            </div>
          )}
          {/* Radix 는 이미 체크된 지금 지도를 눌러도 부른다 — 그대로 두면 탭이 마킹 탭으로 바뀌고 뒤로가기 기록이 쌓인다. */}
          <DropdownMenu.RadioGroup value={mapId} onValueChange={(id) => id !== mapId && navigate(`/maps/${id}`)}>
            {maps.data?.items.map((map) => (
              <DropdownMenu.RadioItem key={map.id} value={map.id} className={ITEM}>
                <span className="min-w-0 flex-1 truncate font-medium text-ink-900">{map.title}</span>
                {map.region && <span className="shrink-0 rounded-md bg-ink-100 px-1.5 py-0.5 text-[0.6875rem] text-ink-500">{map.region}</span>}
                {/* 체크 자리를 늘 비워 둬서 지금 지도만 줄 끝이 들쭉날쭉하지 않게 한다. */}
                <span className="flex size-4 shrink-0 items-center justify-center">
                  <DropdownMenu.ItemIndicator>
                    <Check size={16} aria-hidden="true" className="text-brand-600" />
                  </DropdownMenu.ItemIndicator>
                </span>
              </DropdownMenu.RadioItem>
            ))}
          </DropdownMenu.RadioGroup>

          <DropdownMenu.Separator className="mx-1 my-1.5 h-px bg-ink-200" />
          <DropdownMenu.Item className={`${ITEM} font-medium text-brand-600`} onSelect={() => navigate('/maps/new')}>
            <Plus size={16} aria-hidden="true" /> 새 지도 만들기
          </DropdownMenu.Item>
          <DropdownMenu.Item className={`${ITEM} text-ink-900`} onSelect={() => navigate('/')}>
            <LayoutGrid size={16} aria-hidden="true" className="text-ink-500" /> 내 지도 목록
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}
