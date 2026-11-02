import { api } from '@/api'
import type { PinCreateRequest } from '@/features/map/model'

import type { BulkPinItemResultDto, LinkHint, LinkPreviewItemDto } from './model'

/**
 * 링크 미리보기(#9). 쓰기 없음. 대화 원문이 아니라 뽑은 URL과 공유 글의 상호명·주소 힌트(#946)만 보낸다.
 * `hints[i]`는 `urls[i]`의 힌트이고 없으면 null 이다. 하나도 없으면 hints 를 싣지 않는다(길이가 다르면 422).
 */
export const previewLinks = (mapId: string, urls: string[], hints: (LinkHint | null)[] = []) =>
  api<{ items: LinkPreviewItemDto[] }>(`/maps/${mapId}/pins/link-preview`, {
    method: 'POST',
    body: JSON.stringify(hints.some(Boolean) ? { urls, hints } : { urls }),
  })

/** 핀 일괄 생성(#9). 항목마다 따로 처리돼 일부가 중복·거절이어도 나머지는 만들어진다. */
export const createPinsBulk = (mapId: string, pins: PinCreateRequest[]) =>
  api<{ results: BulkPinItemResultDto[] }>(`/maps/${mapId}/pins/bulk`, { method: 'POST', body: JSON.stringify({ pins }) })
