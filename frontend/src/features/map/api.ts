import { api } from '@/api'

import type { PinDto } from './model'

export const fetchPins = (mapId: string) => api<PinDto[]>(`/maps/${mapId}/pins`)
