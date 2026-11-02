import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { MemoryRouter } from 'react-router'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import { useToastStore } from '@/features/shell/toast'

import { dismissSuggestion, fetchAgent } from './api'
import AgentSheet from './AgentSheet'
import type { AgentStateDto, AgentSuggestionDto } from './model'
import { agentEventHandlers, agentKeys } from './queries'

const MAP = 'map_1'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  server.resetHandlers()
  resetScenario('happy-path')
})
afterAll(() => server.close())

function setup(state?: AgentStateDto) {
  // 상태를 넣어 줬으면 마운트하며 다시 받지 않는다 — 그 상태 그대로의 화면을 본다.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: state ? Infinity : 0 } } })
  if (state) client.setQueryData(agentKeys.state(MAP), state)
  const onClose = vi.fn()
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AgentSheet mapId={MAP} onClose={onClose} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { client, onClose }
}

const split: AgentSuggestionDto = {
  id: 'sug_split',
  diagnosis: 'split',
  category: '카페',
  title: '의견이 갈린 핀이 있어요',
  analysis: { conflict_type: 'same_axis', axes: [{ label: '조용한 곳', like_side: '원함 2', against_side: '원하지 않음 1' }] },
  advice: [
    { segments: [{ kind: 'pin', pin_id: 'p1', text: '성수 카페' }, { kind: 'text', text: '에 ♥ 2, 반대 1이에요' }], is_guess: false },
    { segments: [{ kind: 'text', text: '분위기를 두고 갈린 것 같아요. ' }, { kind: 'quote', reaction_id: 'r1', text: '너무 시끄러워요' }], is_guess: true },
  ],
  actions: [{ index: 0, type: 'show_pins', label: '갈린 핀 보기', params: { pin_ids: ['p1'] } }],
  created_at: '2026-10-30T00:00:00Z',
  expires_at: '2026-10-31T00:00:00Z',
}
const state = (s: AgentSuggestionDto | null, unseen = false): AgentStateDto => ({
  settings: { enabled: true, updated_by: null, updated_at: null },
  active_suggestion: s,
  has_unseen: unseen,
  summaries: [],
})

describe('핑고 AI 조언 시트(#516, #536, #582)', () => {
  it('열면 제안을 보여 주고 열람을 기록해 점을 끈다', async () => {
    const { client } = setup()
    expect(await screen.findByText('확정 리스트에 카페가 아직 없어요')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '카페 추천 받기' })).toBeInTheDocument()
    await waitFor(() => expect(client.getQueryData<AgentStateDto>(agentKeys.state(MAP))?.has_unseen).toBe(false))
    expect((await fetchAgent(MAP)).has_unseen).toBe(false)
  })

  it('갈림 제안은 충돌 지점과 ♥/반대 쪽을 보이고, 추정 문장에만 「추정」을 붙인다', () => {
    setup(state(split))
    expect(screen.getByText('같은 점을 두고 의견이 반대예요')).toBeInTheDocument()
    expect(screen.getByText(/좋음 쪽 · 원함 2/)).toBeInTheDocument()
    expect(screen.getByText(/반대 쪽 · 원하지 않음 1/)).toBeInTheDocument()
    expect(screen.getAllByText('추정')).toHaveLength(1)
    // 구성원 의견은 인용 모양으로, 이름 없이.
    expect(screen.getByText('너무 시끄러워요').tagName).toBe('Q')
  })

  it('이미 처리된 제안(409)이면 알리고 상태를 다시 받는다', async () => {
    const before = await fetchAgent(MAP)
    await dismissSuggestion(before.active_suggestion!.id) // 다른 구성원이 먼저 닫았다
    const { client } = setup(before)
    await userEvent.click(screen.getByRole('button', { name: '카페 추천 받기' }))
    await waitFor(() => expect(useToastStore.getState().toast?.message).toBe('다른 구성원이 먼저 처리한 제안이에요'))
    await waitFor(() => expect(client.getQueryData<AgentStateDto>(agentKeys.state(MAP))?.active_suggestion).toBeNull())
    expect(await screen.findByText('지금은 따로 드릴 제안이 없어요')).toBeInTheDocument()
  })
})

describe('agent.* 이벤트(페이로드로 고침, 멱등)', () => {
  const msg = (data: unknown) => new MessageEvent('message', { data: JSON.stringify(data) })

  it('suggested → 점 켜기, 같은 이벤트 두 번은 같은 결과, resolved → 비우기, 끄기 → 비우기', () => {
    const client = new QueryClient()
    client.setQueryData(agentKeys.state(MAP), state(null))
    const on = agentEventHandlers(client, MAP)
    const get = () => client.getQueryData<AgentStateDto>(agentKeys.state(MAP))!

    on['agent.suggested'](msg(split))
    on['agent.suggested'](msg(split))
    expect(get()).toMatchObject({ active_suggestion: { id: 'sug_split' }, has_unseen: true })

    on['agent.resolved'](msg({ suggestion_id: 'other', status: 'dismissed', resolved_action_type: null }))
    expect(get().active_suggestion?.id).toBe('sug_split')
    on['agent.resolved'](msg({ suggestion_id: 'sug_split', status: 'accepted', resolved_action_type: 'show_pins' }))
    expect(get()).toMatchObject({ active_suggestion: null, has_unseen: false })

    on['agent.suggested'](msg(split))
    on['agent.settings_changed'](msg({ enabled: false, updated_by: 'user_2' }))
    expect(get()).toMatchObject({ settings: { enabled: false, updated_by: 'user_2' }, active_suggestion: null, has_unseen: false })
  })
})

describe('우리 조건 요약(#589)', () => {
  it('이름 없이 개수만, 비어 있지 않은 칸만, 추천 대상 카테고리엔 추천 버튼', async () => {
    setup()
    expect(await screen.findByText('우리 조건 요약')).toBeInTheDocument()
    expect(screen.getByText('매운 곳 제외 · 1명')).toBeInTheDocument()
    expect(screen.getByText('횟집 원함 · 2명')).toBeInTheDocument()
    expect(screen.getByText('체인점 · 원함 1 / 피함 1')).toBeInTheDocument()
    expect(screen.getByText('더 적어 주면 반영돼요 · 1건')).toBeInTheDocument()
    expect(screen.getByText('추천이 거르지 않아요 · 1건')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '이 조건으로 음식점 추천 받기' })).toBeInTheDocument()
  })

  it('agent.summary_updated 는 그 카테고리만 갈아끼우고 점은 켜지 않는다', async () => {
    const client = new QueryClient()
    const base = await fetchAgent(MAP)
    client.setQueryData(agentKeys.state(MAP), { ...base, has_unseen: false })
    const on = agentEventHandlers(client, MAP)
    const food = { ...base.summaries[0], must_keep: [] }
    const cafe = { ...base.summaries[0], category: '카페' as const }
    on['agent.summary_updated'](new MessageEvent('message', { data: JSON.stringify(food) }))
    on['agent.summary_updated'](new MessageEvent('message', { data: JSON.stringify(cafe) }))
    const s = client.getQueryData<AgentStateDto>(agentKeys.state(MAP))!
    expect(s.summaries.map((x) => [x.category, x.must_keep.length])).toEqual([['음식점', 0], ['카페', 1]])
    expect(s.has_unseen).toBe(false)
  })
})

describe('지도 현황 문단과 우리 데이터 줄(#1169)', () => {
  const paragraph = '카페는 거의 정해졌고, 음식점은 갈린 곳 하나만 남았어요. 출발이 5일 남았으니 음식점부터 보면 좋겠어요.'
  const withStatus: AgentStateDto = { ...state(null), status: { paragraph, updated_at: '2026-11-03T00:00:00Z' } }
  const facts: AgentSuggestionDto['facts'] = [
    {
      fact_key: 'parking',
      value: 'yes',
      segments: [{ kind: 'text', text: '우리 데이터: ' }, { kind: 'pin', pin_id: 'p1', text: '성수 카페' }, { kind: 'text', text: '은 주차할 수 있는 곳으로 나와요' }],
    },
    {
      fact_key: 'quiet',
      value: 'no',
      segments: [
        { kind: 'text', text: '우리 데이터: ' },
        { kind: 'pin', pin_id: 'p1', text: '성수 카페' },
        { kind: 'text', text: '은 조용한 곳이 아니라고 나와요. 데이터가 틀릴 수 있어요' },
      ],
    },
  ]
  const unknownFact: NonNullable<AgentSuggestionDto['facts']>[number] = {
    fact_key: 'parking',
    value: 'unknown',
    segments: [{ kind: 'text', text: '우리 데이터로는 ' }, { kind: 'pin', pin_id: 'p1', text: '성수 카페' }, { kind: 'text', text: '이 주차할 수 있는 곳인지 몰라요' }],
  }

  it('현황 문단은 모드 스위치 아래, 제안보다 위에 「AI」 배지와 서버 문단 그대로', () => {
    setup({ ...withStatus, active_suggestion: split })
    const section = screen.getByRole('region', { name: '지금 지도 현황' })
    expect(section).toHaveTextContent('AI')
    expect(screen.getByText(paragraph)).toBeInTheDocument()
    // 문서 순서: 현황 문단 → 제안 제목.
    const title = screen.getByText('의견이 갈린 핀이 있어요')
    expect(section.compareDocumentPosition(title) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it.each([
    ['없음', state(null)],
    ['null', { ...state(null), status: null }],
  ])('현황이 %s이면 자리를 두지 않는다', (_, s) => {
    setup(s)
    expect(screen.queryByRole('region', { name: '지금 지도 현황' })).not.toBeInTheDocument()
    expect(screen.getByText('지금은 따로 드릴 제안이 없어요')).toBeInTheDocument()
  })

  it('모드가 꺼져 있으면 「꺼져 있어요」 한 줄만 — 현황 문단도 없다', () => {
    setup({ ...withStatus, settings: { enabled: false, updated_by: null, updated_at: null } })
    expect(screen.getByText(/꺼져 있어요/)).toBeInTheDocument()
    expect(screen.queryByText(paragraph)).not.toBeInTheDocument()
  })

  it.each([
    ['없음', undefined],
    ['빈 목록', []],
  ])('facts가 %s이면 「우리 데이터」를 그리지 않는다', (_, f) => {
    setup(state({ ...split, facts: f }))
    expect(screen.queryByText('우리 데이터')).not.toBeInTheDocument()
  })

  it('facts 두 줄은 행동 버튼 위에 조각대로 잇고, 핀 이름은 핀 모양, 판정 문구를 더하지 않는다', () => {
    setup(state({ ...split, facts }))
    const head = screen.getByRole('heading', { name: '우리 데이터' })
    const lines = head.parentElement!.querySelectorAll('li')
    expect(lines).toHaveLength(2)
    expect(lines[0]).toHaveTextContent('우리 데이터: 성수 카페은 주차할 수 있는 곳으로 나와요')
    expect(lines[1]).toHaveTextContent(/^우리 데이터: 성수 카페은 조용한 곳이 아니라고 나와요\. 데이터가 틀릴 수 있어요$/)
    expect(lines[0].querySelector('strong')).toHaveTextContent('성수 카페')
    const button = screen.getByRole('button', { name: '갈린 핀 보기' })
    expect(head.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  const lineIcons = () =>
    [...screen.getByRole('heading', { name: '우리 데이터' }).parentElement!.querySelectorAll('li')].map((li) => li.querySelector('svg')!.getAttribute('class'))

  it('참·거짓은 같은 「데이터」 아이콘 — ✓·✕로 판정하지 않는다(#1182)', () => {
    setup(state({ ...split, facts }))
    const [yes, no] = lineIcons()
    expect(yes).toContain('lucide-database')
    expect(no).toBe(yes)
    expect(document.querySelector('.lucide-check, .lucide-x')).toBeNull()
  })

  it('모름만 물음표 아이콘(#1182)', () => {
    setup(state({ ...split, facts: [facts[0], unknownFact] }))
    const [yes, unknown] = lineIcons()
    expect(yes).toContain('lucide-database')
    expect(unknown).toMatch(/lucide-circle-(help|question-mark)/)
  })

  it('agent.suggested 로 온 제안의 facts도 다시 부르지 않고 그린다', async () => {
    const { client } = setup(state(null))
    const on = agentEventHandlers(client, MAP)
    on['agent.suggested'](new MessageEvent('message', { data: JSON.stringify({ ...split, facts }) }))
    expect(await screen.findByRole('heading', { name: '우리 데이터' })).toBeInTheDocument()
  })

  it('목 서버 시드 지도는 현황 문단을 보낸다', async () => {
    setup()
    expect(await screen.findByRole('region', { name: '지금 지도 현황' })).toBeInTheDocument()
  })
})
