import type { components } from '@pingo/contracts/src/types/api'

export type UserDto = components['schemas']['User']
/** 지금은 응답 그대로다. 화면용으로 바꿀 게 생기면 여기서 바꾸고 화면은 그대로 둔다. */
export type User = UserDto

/** 탈퇴한 계정으로 다시 로그인하려는 중의 안내(#855). 남은 날수는 서버가 센다 — 화면은 날짜를 계산하지 않는다. */
export type PendingAccountDto = components['schemas']['PendingAccount']
export type PendingChoice = components['schemas']['PendingChoiceRequest']['choice']

/** 되살릴 수 있는 마지막 시각 — 「11.2 (월) 15:00」. 다른 화면의 날짜 표기(`M.D (요일)`)에 시각만 붙였다. */
export function formatRestoreUntil(iso: string): string {
  const d = new Date(iso)
  const time = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  return `${d.getMonth() + 1}.${d.getDate()} (${'일월화수목금토'[d.getDay()]}) ${time}`
}
