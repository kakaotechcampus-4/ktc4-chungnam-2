# 권한 모델 — 롤 → 범위 + 액션

작성 기준: 최종기획안 15-1절 + 기술 멘토링 피드백
멘토: "롤로 조건 판단을 하지 말고, 롤 → 접근 가능 범위 + 가능한 액션으로 권한이 내려오게 설계하라. 나중에 역할 추가가 쉽다."

기획안 15-1은 행동 4개를 각각 "누가 할 수 있는가"로 나열한 표다. 기능이 맞긴 하지만, 이 형태로 코드를 짜면 액션이 늘 때마다(#8 강퇴, 미래의 새 역할) if문이 하나씩 늘어난다. 대신 아래처럼 **역할이 갖는 (범위, 액션 집합)** 으로 뒤집는다. `authz` 모듈은 이 선언을 해석하는 판정 엔진 하나만 가지면 되고, 새 역할 추가는 표에 행을 하나 넣는 문제가 된다.

## 역할 정의

```yaml
member:                      # 지도에 참여한 모든 구성원 — 기본 역할
  scope:
    map: own                 # 자신이 속한 지도
  actions:
    - pin.create
    - pin.react               # ♥/△/🚫 등록·수정
    - pin.revert               # 반응으로 바뀐 상태 되돌리기 — "누구나" (15-1)
    - shortlist.add
    - shortlist.remove         # "구성원 누구나" (5-3, 15-1)
    - evidence.add
    - recommend.request        # 「추천 받기」
    - recommend.publish        # 「지도에 올리기」 — 단, candidate.requested_by 본인만(아래 author 참고)

author:                       # evidence_line 또는 candidate를 만든 당사자에게 얹히는 추가 범위
  scope:
    evidence_line: own         # 자기가 쓴 줄만
    candidate: own              # 자기가 요청한 run의 비공개 후보만
  actions:
    - evidence.disable          # '-'로 빼기 — "자기가 쓴 것만" (5-5)
    - candidate.view_private     # 게시 전 비공개 후보 열람 (5-5-1)

owner:                        # 지도 생성자. member 전체 + 아래 추가
  scope:
    map: own
  actions:
    - member.kick               # v2, #8
    - map.settings.edit
```

역할은 배타적이지 않고 누적된다 — 한 사용자는 `member` + (자기 evidence에 한해) `author` + (자기 지도에 한해) `owner`를 동시에 가질 수 있다. 판정은 "이 액션이 이 리소스의 scope 안에 있는가"로 계산한다.

## API 계약과의 연결

모든 리소스 응답(`api-spec.yaml`)은 요청자 기준으로 계산된 `permissions` 객체를 인라인으로 포함한다. **프론트는 역할 이름이나 규칙을 몰라도 되고, 내려온 boolean만 본다.**

```json
{
  "id": "pin_123",
  "kind": "AI추천",
  "permissions": {
    "can_react": true,
    "can_add_to_shortlist": true,
    "can_remove_from_shortlist": true,
    "can_revert": true
  }
}
```

```json
{
  "id": "evi_45",
  "author_id": "user_9",
  "permissions": { "can_disable": false }   // 요청자가 author_9가 아니므로 false
}
```

이렇게 하면 FE는 "권한 규칙"을 다시 구현하지 않는다 — 버튼의 disabled 여부를 서버가 계산해서 내려준 값 그대로 쓴다. 이게 산출물 B(API 계약)와 이 문서가 맞물리는 지점이다.

## 15-1 표와의 매핑 (검증용)

| 기획안 15-1 행동 | 이 모델에서의 표현 |
|---|---|
| 확정 리스트 추가·제외 — 구성원 누구나 | `member.actions: [shortlist.add, shortlist.remove]` |
| 근거 리스트에서 항목 빼기 — 자기가 쓴 것만 | `author.scope.evidence_line: own`, `author.actions: [evidence.disable]` |
| 핀 되돌리기 — 구성원 누구나 | `member.actions: [pin.revert]` |
| 반경 조정 — 별도 권한 불필요 | 반경 사유도 `evidence_line`이므로 위 규칙을 그대로 상속. 별도 액션 없음 |

## v2 확장 지점

`owner.actions`에 `member.kick`이 이미 자리를 잡아뒀다 — #8 구현 시 `authz`에 액션 하나만 추가하면 되고 다른 모듈은 건드리지 않는다. 이게 멘토가 말한 "역할 추가가 쉽다"의 실제 이득이다.
