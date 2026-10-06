import type { components } from '@pingo/contracts/src/types/api'

export type PinDto = components['schemas']['Pin']
/** 지금은 응답 그대로다. 화면용으로 바꿀 게 생기면(반응 집계 등) 여기서 바꾸고 화면은 그대로 둔다. */
export type Pin = PinDto
