import { api } from '@/api'

import type { CreditBalanceDto } from './model'

/** 내 잔액·가격·후기 보상(#432). 게스트는 403 GUEST_NOT_ALLOWED. */
export const fetchCredits = () => api<CreditBalanceDto>('/credits/me')
