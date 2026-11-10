import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { http, HttpResponse } from 'msw'
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
    expect(screen.getByText('매운 곳 제외 (1명)')).toBeInTheDocument()
    expect(screen.getByText('횟집 원함 (2명)')).toBeInTheDocument()
    expect(screen.getByText('체인점 (원하는 사람 1명, 피하는 사람 1명)')).toBeInTheDocument()
    expect(screen.getByText('더 적어 주면 반영돼요 (1건)')).toBeInTheDocument()
    expect(screen.getByText('추천에서 거르지 않는 조건 (1건)')).toBeInTheDocument()
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
    // 시트의 닫기 ✕(#1690)는 판정이 아니라 데이터 줄 안에서만 본다.
    expect(screen.getByRole('heading', { name: '우리 데이터' }).parentElement!.querySelector('.lucide-check, .lucide-x')).toBeNull()
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

  describe('웹 요약(#1217, agent-v2 6.8)', () => {
    type Web = NonNullable<typeof unknownFact.web>
    const found: Web = {
      status: 'found',
      notice: null,
      statements: [
        { text: '가게 앞에 차 두세 대를 댈 수 있다고 적혀 있어요', source_url: 'https://blog.example.com/123', source_name: 'blog.example.com' },
        { text: '근처 공영주차장을 쓰라는 글이 있어요', source_url: 'http://cafe.example.org/p/9', source_name: 'cafe.example.org' },
      ],
      checked_at: '2026-11-03T12:00:00+09:00',
    }
    const factLines = () => [...screen.getByRole('heading', { name: '우리 데이터' }).parentElement!.querySelectorAll(':scope > ul > li')]

    it('found는 「확인되지 않음」 머리 + 서버 문장 그대로 + 문장마다 출처 이름 링크(새 탭)', () => {
      setup(state({ ...split, facts: [facts[0], { ...unknownFact, web: found }] }))
      const block = screen.getByRole('heading', { name: 'AI 웹 요약 (확인 안 됨)' }).parentElement!
      for (const s of found.statements) {
        expect(screen.getByText(s.text)).toBeInTheDocument()
        const link = screen.getByRole('link', { name: `${s.source_name}에서 보기, 새 탭` })
        expect(link).toHaveTextContent(s.source_name)
        expect(link).toHaveAttribute('href', s.source_url)
        expect(link).toHaveAttribute('target', '_blank')
        expect(link).toHaveAttribute('rel', 'noopener noreferrer')
      }
      // 판정 아이콘·색을 붙이지 않는다(2절 3번 예외 — 결론·판정 없음).
      expect(block.querySelector('.lucide-check, .lucide-x, [class*="good"], [class*="bad"]')).toBeNull()
    })

    it('웹 요약은 web이 있는 그 줄 아래에만 붙는다', () => {
      setup(state({ ...split, facts: [facts[0], { ...unknownFact, web: found }] }))
      const [plain, withWeb] = factLines()
      expect(plain).not.toHaveTextContent('확인 안 됨')
      expect(plain.querySelector('a')).toBeNull()
      expect(withWeb).toHaveTextContent('이 주차할 수 있는 곳인지 몰라요')
      expect(withWeb).toHaveTextContent('AI 웹 요약 (확인 안 됨)')
    })

    it.each([['not_found' as const], ['paused' as const]])('%s는 서버 notice 글을 그대로 한 줄 — 화면이 문구를 적지 않는다', (status) => {
      // 실제 문구가 아닌 글을 줘서 화면이 자기 문구로 바꾸지 않는지 본다.
      const notice = `서버가 보낸 ${status} 안내 글`
      setup(state({ ...split, facts: [{ ...unknownFact, web: { status, notice, statements: [], checked_at: found.checked_at } }] }))
      expect(screen.getByText(notice)).toBeInTheDocument()
      expect(screen.queryByText(/확인 안 됨|웹에서도 찾지 못했어요|웹 확인을 쉬고/)).not.toBeInTheDocument()
      expect(screen.queryByRole('link')).not.toBeInTheDocument()
    })

    it.each([
      ['web이 없는 줄', unknownFact],
      ['statements가 빈 found', { ...unknownFact, web: { ...found, statements: [] } }],
    ])('%s은 블록이 없다', (_, line) => {
      setup(state({ ...split, facts: [line] }))
      const [only] = factLines()
      expect(only).toHaveTextContent(/^우리 데이터로는 성수 카페이 주차할 수 있는 곳인지 몰라요$/)
      expect(screen.queryByText(/확인 안 됨/)).not.toBeInTheDocument()
      expect(screen.queryByRole('link')).not.toBeInTheDocument()
    })
  })

  it('목 서버 시드 지도는 현황 문단을 보낸다', async () => {
    setup()
    expect(await screen.findByRole('region', { name: '지금 지도 현황' })).toBeInTheDocument()
  })
})

describe('핑고가 한 일과 살펴본 상태(#1300)', () => {
  const steps = [
    { stage: '감지', role: '계산', by: 'code', by_detail: null, text: '의견이 갈린 핀 1곳을 찾았어요' },
    { stage: '조사', role: '지휘', by: 'ai', by_detail: '모델 → 코드', text: '반대 사유 3개를 읽었어요' },
  ] satisfies AgentSuggestionDto['steps']

  it('제안 아래 「핑고가 한 일 보기」를 누르면 단계 · 누가 칩 · 문장이 한 줄씩 펼쳐진다', async () => {
    setup(state({ ...split, steps }))
    const toggle = screen.getByRole('button', { name: '핑고가 한 일 보기' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('list', { name: '핑고가 한 일' })).not.toBeInTheDocument()
    await userEvent.click(toggle)
    const log = screen.getByRole('list', { name: '핑고가 한 일' })
    expect(log.querySelectorAll('li')).toHaveLength(2)
    expect(screen.getByText('의견이 갈린 핀 1곳을 찾았어요')).toBeInTheDocument()
    expect(screen.getByText('모델 → 코드')).toBeInTheDocument()
    expect(within(log).getByText('AI')).toHaveClass('tag-ai')
    expect(within(log).getByText('코드')).toHaveClass('tag-neutral')
    expect(screen.getByRole('button', { name: '핑고가 한 일 접기' })).toHaveAttribute('aria-expanded', 'true')
  })

  it('steps가 없거나 비면 토글을 그리지 않는다', () => {
    setup(state({ ...split, steps: [] }))
    expect(screen.queryByRole('button', { name: /핑고가 한 일/ })).not.toBeInTheDocument()
  })

  it('살펴본 시각을 상대 시각으로, 제안이 없으면 서버 notice 를 그대로 보인다', () => {
    const checked = new Date(Date.now() - 12 * 60_000).toISOString()
    setup({ ...state(null), observation: { checked_at: checked, notice: '오늘은 자세히 살펴보는 횟수를 다 썼어요. 내일 다시 볼게요' } })
    expect(screen.getByText('핑고가 12분 전에 지도를 살펴봤어요')).toBeInTheDocument()
    expect(screen.getByText('지금은 따로 드릴 제안이 없어요')).toBeInTheDocument()
    expect(screen.getByText('오늘은 자세히 살펴보는 횟수를 다 썼어요. 내일 다시 볼게요')).toBeInTheDocument()
  })

  it('관찰한 적이 없으면(checked_at null) 시각 줄을 두지 않는다', () => {
    setup({ ...state(null), observation: { checked_at: null, notice: null } })
    expect(screen.queryByText(/지도를 살펴봤어요/)).not.toBeInTheDocument()
  })

  it('시트 조회가 실패하면 「다시 시도」로 다시 받는다', async () => {
    let calls = 0
    server.use(
      http.get('*/maps/:mapId/agent', () => {
        calls += 1
        return calls === 1 ? HttpResponse.json({ code: 'INTERNAL', message: 'x' }, { status: 500 }) : HttpResponse.json(state(null))
      }),
    )
    setup()
    await userEvent.click(await screen.findByRole('button', { name: '다시 시도' }))
    expect(await screen.findByText('지금은 따로 드릴 제안이 없어요')).toBeInTheDocument()
    expect(screen.queryByText('조언을 불러오지 못했어요')).not.toBeInTheDocument()
  })
})

describe('막힌 곳 지켜보기와 충돌 선언(#1348)', () => {
  const hoursAgo = (h: number) => new Date(Date.now() - h * 3600_000).toISOString()
  const tracking: NonNullable<AgentStateDto['tracking']> = [
    { suggestion_id: 't1', diagnosis: 'stall', category: '음식점', status: 'watching', text: '음식점 · 추천 받기 뒤로 지켜보는 중', since: hoursAgo(2), tried: [] },
    { suggestion_id: 't2', diagnosis: 'category_gap', category: '카페', status: 'resolved', text: '카페 · 풀렸어요 — 새 핀이 올라왔어요', since: hoursAgo(5), tried: [] },
    { suggestion_id: 't3', diagnosis: 'split', category: '관광지', status: 'declared', text: '관광지 · 해 본 것을 남겼어요', since: hoursAgo(26), tried: [] },
  ]
  const tried: NonNullable<AgentSuggestionDto['tried']> = [
    // 순서가 섞여 와도 오래된 것부터 그린다.
    { action_type: 'search_place', label: '음식점 검색', accepted_at: hoursAgo(4) },
    { action_type: 'open_recommend', label: '음식점 추천 받기', accepted_at: hoursAgo(9) },
  ]
  const triedLabels = () => [...screen.getByRole('heading', { name: '해 본 것' }).parentElement!.querySelectorAll('li')].map((li) => li.firstChild?.nextSibling?.firstChild?.textContent)

  it('지켜보는 곳 셋 상태 — 서버 문구 그대로, 지켜보는 중만 「N시간째」를 따로 붙인다', () => {
    setup({ ...state(null), tracking })
    const list = screen.getByRole('heading', { name: '핑고가 지켜보는 곳' }).parentElement!
    const rows = [...list.querySelectorAll('li')]
    expect(rows).toHaveLength(3)
    expect(within(rows[0]).getByText('음식점 · 추천 받기 뒤로 지켜보는 중', { exact: false })).toBeInTheDocument()
    expect(within(rows[0]).getByText('2시간째')).toBeInTheDocument()
    expect(within(rows[0]).getByRole('img', { name: '지켜보는 중' })).toBeInTheDocument()
    expect(within(rows[1]).getByText('5시간 전')).toBeInTheDocument()
    expect(within(rows[1]).getByRole('img', { name: '풀림' })).toBeInTheDocument()
    expect(within(rows[2]).getByText('1일 전')).toBeInTheDocument()
    expect(within(rows[2]).getByRole('img', { name: '해 본 것을 남김' })).toBeInTheDocument()
    // 숫자는 서버 문구에 섞지 않는다 — 문구 조각은 그대로다.
    expect(within(rows[0]).getByText('2시간째').parentElement!.firstChild?.textContent).toBe('음식점 · 추천 받기 뒤로 지켜보는 중')
  })

  it.each([
    ['없으면', undefined],
    ['빈 목록이면', []],
  ])('tracking이 %s 자리를 두지 않는다', (_, t) => {
    setup({ ...state(null), tracking: t })
    expect(screen.queryByRole('heading', { name: '핑고가 지켜보는 곳' })).not.toBeInTheDocument()
  })

  it('모드가 꺼져 있으면 지켜보는 곳을 그리지 않는다', () => {
    setup({ ...state(null), tracking, settings: { enabled: false, updated_by: null, updated_at: null } })
    expect(screen.queryByRole('heading', { name: '핑고가 지켜보는 곳' })).not.toBeInTheDocument()
  })

  it('attempt 1(다음 방법)은 「두 번째 방법」 칩과 해 본 것(오래된 것부터), 버튼은 그대로', () => {
    setup(state({ ...split, attempt: 1, tried }))
    expect(screen.getByText('두 번째 방법')).toHaveClass('tag')
    expect(triedLabels()).toEqual(['음식점 추천 받기', '음식점 검색'])
    expect(screen.getByRole('button', { name: '갈린 핀 보기' })).toBeInTheDocument()
  })

  it('attempt 2(충돌 선언)는 버튼 없이 서버 문장만 — 문장이 해 본 것을 나열해 목록을 따로 두지 않는다, 닫기는 남는다', () => {
    const declared = { ...split, analysis: null, attempt: 2, tried, actions: [], advice: [{ segments: [{ kind: 'text' as const, text: '어떤 조건을 지킬지는 여러분이 정해요' }], is_guess: false }] }
    setup(state(declared))
    expect(screen.queryByText('두 번째 방법')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '해 본 것' })).not.toBeInTheDocument()
    expect(screen.getByText('어떤 조건을 지킬지는 여러분이 정해요')).toBeInTheDocument()
    expect(screen.getAllByRole('button').map((b) => b.textContent)).toEqual(expect.not.arrayContaining(['갈린 핀 보기']))
    expect(screen.getByRole('button', { name: '이 제안 닫기' })).toBeInTheDocument()
  })

  it('attempt가 없으면 0 — 칩도 해 본 것도 없다', () => {
    setup(state({ ...split, tried }))
    expect(screen.queryByText('두 번째 방법')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '해 본 것' })).not.toBeInTheDocument()
  })

  it('목 서버 기본 시나리오: 지켜보는 중 하나와 풀림 하나', async () => {
    setup()
    const head = await screen.findByRole('heading', { name: '핑고가 지켜보는 곳' })
    expect(head.parentElement!.querySelectorAll('li')).toHaveLength(2)
    expect(screen.getByText('음식점 · 추천 받기 뒤로 지켜보는 중', { exact: false })).toBeInTheDocument()
  })

  it('목 서버 agent-declared: 충돌 선언 카드, 작업 기록에 「후속 확인」 줄', async () => {
    resetScenario('agent-declared')
    setup()
    expect(await screen.findByText('음식점은 해 본 방법으로 풀리지 않았어요')).toBeInTheDocument()
    // 해 본 것은 서버 문장이 말한다 — 목록은 없다.
    expect(screen.getByText('추천 받기와 장소 검색을 해 봤지만 반대 의견 뒤로 음식점에 새 핀이 없어요')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '해 본 것' })).not.toBeInTheDocument()
    // 충돌 선언은 버튼이 없다(우리 조건 요약의 추천 버튼은 제안 밖이다).
    expect(screen.queryByRole('button', { name: /^음식점 (추천 받기|검색)$/ })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '핑고가 한 일 보기' }))
    expect(screen.getByText('후속 확인')).toBeInTheDocument()
    expect(screen.getByText('장소 검색 뒤로 4시간 동안 음식점에 새 핀이 없었어요')).toBeInTheDocument()
  })
})
