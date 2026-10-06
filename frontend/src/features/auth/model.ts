import type { components } from '@pingo/contracts/src/types/api'

export type UserDto = components['schemas']['User']
/** 지금은 응답 그대로다. 화면용으로 바꿀 게 생기면 여기서 바꾸고 화면은 그대로 둔다. */
export type User = UserDto

/**
 * 로그인 실패 안내. BE 콜백은 실패해도 JSON 대신 항상 진입점으로 302 하면서 `?login_error=<값>`을 붙인다(docs/api-spec.yaml
 * `/auth/kakao/callback`): cancelled(카카오 화면에서 취소) · invalid_state · kakao_failed · server_error.
 * 값이 없으면 안내할 게 없다(null). 모르는 값도 로그인이 안 된 건 같으니 일반 문구로 안내한다.
 */
export function loginErrorMessage(code: string | null): string | null {
  if (!code) return null
  if (code === 'cancelled') return '로그인을 취소했어요'
  return '로그인하지 못했어요. 다시 시도해 주세요'
}
