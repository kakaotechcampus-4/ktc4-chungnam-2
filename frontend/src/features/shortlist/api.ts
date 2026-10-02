import { api } from '@/api'

import type { ShortlistItemDto } from './model'

export const addToShortlist = (mapId: string, pinId: string) =>
  api<ShortlistItemDto>(`/maps/${mapId}/shortlist`, { method: 'POST', body: JSON.stringify({ pin_id: pinId }) })
