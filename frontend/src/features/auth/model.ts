import type { components } from '@pingo/contracts/src/types/api'

export type UserDto = components['schemas']['User']
/** 지금은 응답 그대로다. 화면용으로 바꿀 게 생기면 여기서 바꾸고 화면은 그대로 둔다. */
export type User = UserDto
export type GuestJoinResult = components['schemas']['GuestJoinResult']

/** 표시 이름 최대 길이 — api-spec `GuestJoinRequest`·`UserUpdateRequest`의 maxLength. 입력칸 글자 수 표시용이고 검증은 서버가 한다. */
export const DISPLAY_NAME_MAX = 50

/**
 * 게스트 전환(#560) 뒤 카카오 콜백이 붙여 돌려보내는 `?guest_merged=` 의 안내.
 * `false`는 카카오 로그인은 됐지만 게스트 기록을 잇지 못했다는 뜻이다(다시 시도하지 않는다, api-spec 콜백 설명).
 */
export function guestMergedMessage(value: string | null): string | null {
  if (value === 'true') return '카카오 계정으로 이어졌어요. 지금까지 남긴 기록이 그대로 있어요'
  if (value === 'false') return '카카오로 로그인했어요. 게스트로 남긴 기록은 옮기지 못했어요'
  return null
}

/** 탈퇴한 계정으로 다시 로그인하려는 중의 안내(#855). 남은 날수는 서버가 센다 — 화면은 날짜를 계산하지 않는다. */
export type PendingAccountDto = components['schemas']['PendingAccount']
export type PendingChoice = components['schemas']['PendingChoiceRequest']['choice']

/** 되살릴 수 있는 마지막 시각 — 「11.2 (월) 15:00」. 다른 화면의 날짜 표기(`M.D (요일)`)에 시각만 붙였다. */
export function formatRestoreUntil(iso: string): string {
  const d = new Date(iso)
  const time = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  return `${d.getMonth() + 1}.${d.getDate()} (${'일월화수목금토'[d.getDay()]}) ${time}`
}
