import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, resetScenario } from '@pingo/contracts/mocks/node'
import { MemoryRouter } from 'react-router'
import { cleanup as cleanupRender } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import { MOCK_SAMPLE } from './__fixtures__/kakaotalkExport'
import { useSheetStore } from '@/features/shell/sheetStore'

import ImportSheet, { ImportSheetHost } from './ImportSheet'
import { closeImport, forgetImport, openImport, resetImport } from './queries'

const MAP = 'map_1'

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' })
  // jsdom 에는 matchMedia 가 없다(넓은 화면 판정·동작 줄이기에 쓴다).
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
})
afterEach(() => {
  server.resetHandlers()
  server.events.removeAllListeners()
  resetScenario('happy-path')
  forgetImport()
})
afterAll(() => {
  server.close()
  vi.unstubAllGlobals()
})

/** 보낸 요청 본문을 모은다 — 대화 원문이 서버로 가지 않는지, 힌트·link_ref 가 맞게 실리는지 본다. */
function capture(path: string) {
  const bodies: Record<string, unknown>[] = []
  server.events.on('request:start', async ({ request }) => {
    if (request.method === 'POST' && new URL(request.url).pathname === path) bodies.push(await request.clone().json())
  })
  return bodies
}

function renderSheet() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ImportSheet mapId={MAP} onClose={() => {}} onOpenOne={() => {}} onSearchName={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** 픽스처 대화가 오간 날(2026-11-02) 하루. */
const DAY = { from: '2026-11-02', to: '2026-11-02' }

/** 종료일은 선택이라 라벨이 「종료일 (선택)」이다. `to`가 없으면 비워 둔다(끝까지 읽기). */
function setRange(range: { from: string; to?: string }) {
  fireEvent.change(screen.getByLabelText('시작일'), { target: { value: range.from } })
  fireEvent.change(screen.getByLabelText(/^종료일/), { target: { value: range.to ?? '' } })
}

/** 기간을 고르고 대화 파일을 넣는다. `button`은 파일 고르는 창을 여는 버튼 이름 — 기간을 고르면 눌리는지 본다. */
async function pickFile(text: string, button: string, range: { from: string; to?: string } = DAY) {
  setRange(range)
  expect(screen.getByRole('button', { name: button })).toBeEnabled()
  await userEvent.upload(screen.getByLabelText('카톡 대화 파일'), new File([text], 'KakaoTalk_Chat.txt', { type: 'text/plain' }))
}

async function paste() {
  renderSheet()
  await pickFile(MOCK_SAMPLE, '대화 파일 넣기')
  // 이름으로 찾기까지 끝나면 후보 라디오가 뜬다.
  await screen.findByRole('radiogroup', { name: '성수 노포 곱창 후보' })
}

describe('카톡 대화에서 핀 가져오기 — 네이버·공유 글 힌트·후보(#1046)', () => {
  it('링크와 상호명·주소 힌트만 같은 길이로 보낸다 — 대화 원문·보낸 사람은 보내지 않는다', async () => {
    const previews = capture(`/maps/${MAP}/pins/link-preview`)
    await paste()

    expect(previews).toHaveLength(1)
    const body = previews[0] as { urls: string[]; hints: unknown[] }
    expect(Object.keys(body).sort()).toEqual(['hints', 'urls'])
    expect(body.urls).toHaveLength(5)
    expect(body.hints).toHaveLength(5)
    expect(body.urls.filter((u) => u.includes('naver.me'))).toHaveLength(4)
    expect(body.hints[0]).toEqual({ name: '해운대 밀면', address: '부산 해운대구 우동' })
    expect(body.hints[2]).toBeNull() // 구글은 이름만이라 힌트를 보내지 않는다
    const sent = JSON.stringify(body)
    for (const secret of ['친구A', '친구B', '오전 1:0', '여기', '이거']) expect(sent).not.toContain(secret)
  })

  it('링크 주소 대신 이름이 보이고, 찾은 방법·주소 후보·이름 후보·같은 곳 묶음이 각각 보인다', async () => {
    await paste()

    // 서버가 상호명·주소로 찾은 곳은 미리 체크
    const hinted = screen.getByRole('checkbox', { name: /해운대 밀면.*이름·주소가 같아서 찾았어요/ })
    expect(hinted).toBeChecked()
    // 번호표로 찾은 다른 링크도 같은 장소 — 한 곳으로 센다
    expect(screen.getByText('위와 같은 곳')).toBeInTheDocument()
    // 이름이 다른 같은 주소 후보는 사람이 확인한다 — 미리 체크하지 않는다
    expect(screen.getByRole('checkbox', { name: /해운대 바다 카페/ })).not.toBeChecked()
    // 이름은 아는데 짝이 없는 곳은 이름으로 찾은 후보에서 고른다 — 고르지 않은 채
    const group = screen.getByRole('radiogroup', { name: '성수 노포 곱창 후보' })
    expect(within(group).getByRole('radio', { name: /여기 없어요/ })).toBeChecked()
    // 번호만 든 링크는 이름을 지어내지 않고 하나씩 찍기로
    expect(screen.getByRole('button', { name: '하나씩 찍기' })).toBeInTheDocument()
    expect(screen.queryByText('https://naver.me/hintA')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '고른 1곳 지도에 찍기' })).toBeEnabled()
  })

  it('고른 곳을 한 번에 찍는다 — 같은 곳은 한 번, 링크 번호는 link_ref, 자체 DB에 없는 곳은 실시간 핀', async () => {
    const bulks = capture(`/maps/${MAP}/pins/bulk`)
    await paste()

    await userEvent.click(screen.getByRole('checkbox', { name: /해운대 바다 카페/ }))
    const group = screen.getByRole('radiogroup', { name: '성수 노포 곱창 후보' })
    await userEvent.click(within(group).getByRole('radio', { name: /성수 노포 곱창/ }))
    await userEvent.click(screen.getByRole('button', { name: '고른 3곳 지도에 찍기' }))

    await waitFor(() => expect(bulks).toHaveLength(1))
    const pins = (bulks[0] as { pins: Record<string, unknown>[] }).pins
    expect(pins).toHaveLength(3)
    expect(pins[0]).toMatchObject({ source: 'search', place_name: '해운대 밀면', link_ref: { provider: 'naver', external_id: 'naver:hintA' } })
    expect(pins.find((p) => p.place_name === '해운대 바다 카페')).toMatchObject({ link_ref: { provider: 'naver', external_id: 'naver:addrB' } })
    expect(pins.find((p) => p.source === 'live')).toEqual({ source: 'live', category: '음식점', kakao_place_id: 'kakao:mock-6', search_query: '성수 노포 곱창' })
    expect(await screen.findByText('3곳을 찍었어요')).toBeInTheDocument()
    expect(screen.getByText('찍은 곳 3개')).toBeInTheDocument()
  })
})

describe('카톡 가져오기 — .txt 파일과 여행 얘기를 한 기간(#1139)', () => {
  it('붙여넣기 칸은 없고, 시작일을 고르기 전에는 파일을 넣지 못한다 — 종료일은 선택이고 앞이면 안내', () => {
    renderSheet()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    const button = screen.getByRole('button', { name: '대화 파일 넣기' })
    expect(button).toBeDisabled()
    expect(screen.getByLabelText(/^종료일/)).toHaveAccessibleDescription('종료일을 비우면 대화 끝까지 읽어요')
    fireEvent.change(screen.getByLabelText('시작일'), { target: { value: '2026-11-02' } })
    expect(button).toBeEnabled()
    fireEvent.change(screen.getByLabelText(/^종료일/), { target: { value: '2026-11-01' } })
    expect(button).toBeDisabled()
    expect(screen.getByLabelText(/^종료일/)).toHaveAccessibleDescription('종료일은 시작일과 같거나 뒤여야 해요')
    fireEvent.change(screen.getByLabelText(/^종료일/), { target: { value: '2026-11-02' } })
    expect(button).toBeEnabled()
  })

  it('종료일을 비우면 시작일부터 대화 끝까지의 링크를 싣는다', async () => {
    const previews = capture(`/maps/${MAP}/pins/link-preview`)
    renderSheet()
    const chat = [
      '2026년 10월 30일 금요일',
      '2026년 10월 30일 오후 9:00, 친구A : 지난번 https://naver.me/hintA',
      '2026년 11월 3일 화요일',
      '2026년 11월 3일 오전 8:00, 친구A : 여기 가자 https://place.map.kakao.com/mock-2',
      '2026년 12월 20일 일요일',
      '2026년 12월 20일 오전 8:00, 친구B : 여기도 https://naver.me/addrB',
    ].join('\n')
    await pickFile(chat, '대화 파일 넣기', { from: '2026-11-01' })

    await waitFor(() => expect(previews).toHaveLength(1))
    expect((previews[0] as { urls: string[] }).urls).toEqual(['https://place.map.kakao.com/mock-2', 'https://naver.me/addrB'])
  })

  it('기간 밖에 보낸 링크는 확인 요청에 싣지 않는다', async () => {
    const previews = capture(`/maps/${MAP}/pins/link-preview`)
    renderSheet()
    const chat = [
      '2026년 10월 30일 금요일',
      '2026년 10월 30일 오후 9:00, 친구A : 지난번 https://naver.me/hintA',
      '2026년 11월 3일 화요일',
      '2026년 11월 3일 오전 8:00, 친구A : 여기 가자 https://place.map.kakao.com/mock-2',
    ].join('\n')
    await pickFile(chat, '대화 파일 넣기', { from: '2026-11-01', to: '2026-11-03' })

    await waitFor(() => expect(previews).toHaveLength(1))
    expect((previews[0] as { urls: string[] }).urls).toEqual(['https://place.map.kakao.com/mock-2'])
    expect(await screen.findByText('지도 링크 1개')).toBeInTheDocument()
  })

  it('그 기간에 링크가 없거나 날짜를 못 읽으면 안내하고 아무것도 보내지 않는다', async () => {
    const previews = capture(`/maps/${MAP}/pins/link-preview`)
    renderSheet()
    await pickFile(MOCK_SAMPLE, '대화 파일 넣기', { from: '2026-10-01', to: '2026-10-02' })
    expect(await screen.findByRole('alert')).toHaveTextContent('이 기간에 지도 링크가 없어요')

    await pickFile('여기 가자 https://naver.me/hintA', '대화 파일 넣기')
    expect(await screen.findByRole('alert')).toHaveTextContent('날짜를 읽지 못했어요')
    expect(previews).toHaveLength(0)
  })

  it('.txt 가 아닌 파일은 읽지 않는다', async () => {
    const user = userEvent.setup({ applyAccept: false })
    renderSheet()
    setRange(DAY)
    await user.upload(screen.getByLabelText('카톡 대화 파일'), new File([MOCK_SAMPLE], 'chat.csv', { type: 'text/csv' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('.txt 파일만 넣을 수 있어요')
    expect(screen.queryByText(/지도 링크 \d+개/)).not.toBeInTheDocument()
  })
  it('확장자가 .txt 가 아니면 형식이 text/plain 이어도 읽지 않는다 — 대문자 .TXT 는 받는다', async () => {
    const user = userEvent.setup({ applyAccept: false })
    renderSheet()
    setRange(DAY)
    await user.upload(screen.getByLabelText('카톡 대화 파일'), new File([MOCK_SAMPLE], 'chat.csv', { type: 'text/plain' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('.txt 파일만 넣을 수 있어요')
    expect(screen.queryByText(/지도 링크 \d+개/)).not.toBeInTheDocument()

    await user.upload(screen.getByLabelText('카톡 대화 파일'), new File([MOCK_SAMPLE], 'KAKAO.TXT', { type: '' }))
    expect(await screen.findByText(/지도 링크 \d+개/)).toBeInTheDocument()
  })

  it('목록이 가득 찬 뒤 새 파일을 넣으면 「더했다」가 아니라 가득 찼다고 알리고, 안내대로 완료된 것을 지우면 더해진다', async () => {
    const lines = (from: number, n: number) =>
      Array.from({ length: n }, (_, i) => `2026년 11월 2일 오전 1:00, 친구A : https://place.map.kakao.com/mock-${from + i}`).join('\n')
    const previews = capture(`/maps/${MAP}/pins/link-preview`)
    renderSheet()
    await pickFile(lines(1, 50), '대화 파일 넣기')
    await screen.findByText('지도 링크 50개')
    await waitFor(() => expect(previews).toHaveLength(5))

    // 가득 찬 목록에 새 링크 — 아무것도 더해지지 않고 이유를 알린다(기간을 좁혀도 풀리지 않는다)
    await pickFile(lines(51, 3), '다른 대화 파일 더하기')
    expect(await screen.findByRole('alert')).toHaveTextContent('목록이 가득 차서 새 링크를 더하지 못했어요')
    expect(screen.getByText('지도 링크 50개')).toBeInTheDocument()
    expect(previews).toHaveLength(5)
  })
})

describe('카톡 가져오기 — 누적·새로고침 뒤 유지·버튼(#1045)', () => {
  it('다른 대화 파일을 넣으면 이전 줄은 남고 새 링크만 더해 확인한다 — 같은 링크는 한 줄', async () => {
    const previews = capture(`/maps/${MAP}/pins/link-preview`)
    await paste()
    await pickFile(
      '2026년 11월 2일 오전 2:00, 친구C : 또 https://naver.me/hintA\n2026년 11월 2일 오전 2:01, 친구C : 새 곳 https://place.map.kakao.com/mock-2',
      '다른 대화 파일 더하기',
    )

    await waitFor(() => expect(previews).toHaveLength(2))
    expect((previews[1] as { urls: string[] }).urls).toEqual(['https://place.map.kakao.com/mock-2'])
    expect(await screen.findByText('지도 링크 6개')).toBeInTheDocument()
    expect(screen.getAllByRole('checkbox', { name: /해운대 밀면.*이름·주소가 같아서 찾았어요/ })).toHaveLength(1)
  })

  it('새로고침해도(화면 메모리를 비워도) 그 지도의 목록·고른 것·찍은 결과가 돌아온다 — 저장소에는 대화 원문과 장소 응답이 없다', async () => {
    const view = await (async () => {
      await paste()
      const group = screen.getByRole('radiogroup', { name: '성수 노포 곱창 후보' })
      await userEvent.click(within(group).getByRole('radio', { name: /성수 노포 곱창/ }))
      await userEvent.click(screen.getByRole('button', { name: '고른 2곳 지도에 찍기' }))
      await screen.findByText('2곳을 찍었어요')
      return screen
    })()
    expect(view).toBeTruthy()

    const saved = window.sessionStorage.getItem(`pingo.kakaoImport.v1.${MAP}`) ?? ''
    expect(saved).toContain('https://naver.me/hintA')
    for (const absent of ['친구A', '여기', '이거', '성수동2가', '"lat"', '오전 1:0']) expect(saved).not.toContain(absent)

    // 새로고침 — 메모리만 비우고 다시 그린다
    cleanupRender()
    resetImport()
    renderSheet()
    expect(await screen.findByText('지도 링크 5개')).toBeInTheDocument()
    expect(await screen.findByText('찍은 곳 2개')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '다른 대화 파일 더하기' })).toBeInTheDocument()
  })

  it('시트가 열린 채 사라져도(화면이 바뀜) 「모달 열림」이 남지 않는다 — 지도 버튼·핑고 조언이 숨은 채 남던 원인', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const view = render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <ImportSheetHost mapId={MAP} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    act(() => openImport(MAP))
    expect(await screen.findByRole('dialog', { name: '카톡 대화에서 핀 가져오기' })).toBeInTheDocument()
    expect(useSheetStore.getState().modalOpen).toBe(true)

    act(() => closeImport())
    await waitFor(() => expect(useSheetStore.getState().modalOpen).toBe(false))

    act(() => openImport(MAP))
    await waitFor(() => expect(useSheetStore.getState().modalOpen).toBe(true))
    view.unmount()
    expect(useSheetStore.getState().modalOpen).toBe(false)
  })
})
