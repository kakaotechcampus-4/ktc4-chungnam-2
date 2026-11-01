import { api } from '@/api'
import type { PinCreateRequest } from '@/features/map/model'

import type { BulkPinItemResultDto, LinkPreviewItemDto } from './model'

/** 링크 미리보기(#9). 쓰기 없음. 대화 원문이 아니라 뽑은 URL만 보낸다. */
export const previewLinks = (mapId: string, urls: string[]) =>
  api<{ items: LinkPreviewItemDto[] }>(`/maps/${mapId}/pins/link-preview`, { method: 'POST', body: JSON.stringify({ urls }) })

/** 핀 일괄 생성(#9). 항목마다 따로 처리돼 일부가 중복·거절이어도 나머지는 만들어진다. */
export const createPinsBulk = (mapId: string, pins: PinCreateRequest[]) =>
  api<{ results: BulkPinItemResultDto[] }>(`/maps/${mapId}/pins/bulk`, { method: 'POST', body: JSON.stringify({ pins }) })
