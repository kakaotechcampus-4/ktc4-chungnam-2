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
    - pin.delete               # "구성원 누구나" (9/4 결정 #25)
    - pin.react               # ♥/△/🚫 등록·수정
    - pin.revert               # 반응으로 바뀐 상태 되돌리기 — "누구나" (15-1)
    - shortlist.add
    - shortlist.remove         # "구성원 누구나" (5-3, 15-1)
    - evidence.add
    - recommend.request        # 「추천 받기」 — 새 run 생성. 누구나 자기 몫의 run을 새로 만들 수 있다
    - recommend.manage         # run 하위 전체(근거·지역확인·실행·결과조회·반경넓히기·재시도) —
                                # 단, run.requested_by 본인만(아래 author 참고). 가드레일1: 대안은
                                # 요청한 사람에게만 먼저 보인다 — 게시 전 run은 본인 것만 조작·열람
    - recommend.publish        # 「지도에 올리기」 — 단, candidate.requested_by 본인만(아래 author 참고)
    - invite.create            # 초대 링크 발급 — "구성원 누구나" (#4 결정, maps/for_Root.md 항목 4)
    - route.recalculate        # 동선 재계산(5-10) — "구성원 누구나" (#103 결정, shortlist/for_Root.md 1번)

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
| 핀 삭제 — 구성원 누구나 (9/4 결정 #25) | `member.actions: [pin.delete]` |
| 근거 리스트에서 항목 빼기 — 자기가 쓴 것만 | `author.scope.evidence_line: own`, `author.actions: [evidence.disable]` |
| 핀 되돌리기 — 구성원 누구나 | `member.actions: [pin.revert]` |
| 반경 조정 — 별도 권한 불필요 | 반경 사유도 `evidence_line`이므로 위 규칙을 그대로 상속. 별도 액션 없음 |
| 초대 링크 발급 — 구성원 누구나 (#4) | `member.actions: [invite.create]` |
| 동선 재계산 — 구성원 누구나 (#103) | `member.actions: [route.recalculate]` |
| AI 추천 run 조작·열람 — 요청한 본인만 (#108, 가드레일1) | `member.actions: [recommend.manage]` + `AUTHOR_CONSTRAINED_ACTIONS` |

## v2 확장 지점

`owner.actions`에 `member.kick`이 이미 자리를 잡아뒀다 — #8 구현 시 `authz`에 액션 하나만 추가하면 되고 다른 모듈은 건드리지 않는다. 이게 멘토가 말한 "역할 추가가 쉽다"의 실제 이득이다.

## 권한을 어디서 강제하는가

이 문서는 지금까지 "무엇을 계산하는가"만 규정했다("표시용 permissions 객체"). 쓰기 시점의
강제 지점은 다음과 같이 고정한다 — `authz`·`pins`를 비롯한 모듈 세션들이 이 시그니처를 두고
서로 기다리지 않고 각자 구현하도록 미리 얼린다(실제로 `backend/authz/guard.py`에 구현·테스트
완료됨, PR #71 멘토 리뷰 대응):

```python
# backend/authz/guard.py
def require(action: str, loader) -> Depends:
    """loader: 리소스를 읽어 {resource: Resource, obj: Any}를 돌려주는 FastAPI 의존성
    (소유 모듈이 제공). 비구성원(role=None)→404, 구성원인데 액션 불가→403.
    Resource.map_id는 항상 loader가 읽은 행에서 나온다 — URL의 mapId를 직접 쓰지 않는다."""

def require_on_map(action: str) -> Depends:
    """리소스가 아직 없는 액션(예: pin.create)용 — 대상이 지도 자신이다."""

def require_map_member() -> Depends:
    """액션 판정이 필요 없는 순수 멤버십 게이트 — 지도 안의 리소스를 조회만 하는 라우트용
    (예: GET /maps/{mapId}/pins). "조회"는 member.actions에 없는 별개의 질문이라 액션 이름을
    재사용하지 않는다."""
```

인증(쿠키/세션 파싱)은 `backend/auth/deps.py::get_current_user`가 라우터의
`APIRouter(dependencies=[...])`로 걸린다 — 각 라우터 파일이 각자 기억해서 부르는 게 아니라
라우터 선언 자체에 박혀 있다. 상세 근거는 `backend/authz/mentor-review-plan.md`,
`backend/auth/mentor-review-plan.md` 참고.

**비구성원 vs 권한 없음의 응답 차이(계약 변경, `docs/CHANGELOG-api.md` 참고):**
- 그 지도의 구성원이 아님 → **404** (존재 자체를 흘리지 않는다)
- 구성원이지만 그 액션이 롤에 없음 → **403**

## 확정 리스트(shortlist) permissions 게이팅 (#65 결정)

`authz`(#36) 구현 중 코드에 먼저 들어갔던 두 규칙을 #7(리스트 탭, PR #80) 도착으로 검증을
마치고 여기 정본으로 확정한다.

1. **pin.kind=="확정" 상태 게이팅** — `can_add_to_shortlist`/`can_remove_from_shortlist`는
   역할·액션 판정(`can()`)이 아니라 핀의 현재 상태로 반전된다: `확정`이 아니면 추가만 가능,
   `확정`이면 제외만 가능. 권한이 아니라 상태 규칙이라 `authz/core.py::_pin_permissions`가
   `permissions_for`에서만 계산하고 `can()`에는 넣지 않는다.
2. **`shortlist_item` 리소스의 `can_add_to_shortlist`는 항상 `false`** — 이미 리스트에 올라간
   항목이라 "추가"가 의미 없다. `can_remove_from_shortlist`만 `can(user, "shortlist.remove",
   resource)`를 따른다. `shortlist/core.py::to_shortlist_item_response`가 이 규칙을 그대로
   써서 응답을 조립하며 통과 확인됨(29 tests).
3. **비공개 AI 후보(visibility=private)는 확정 리스트로 직접 승격할 수 없다** — 소유자 본인이
   자기 비공개 후보를 열람하는 것과, 그 핀을 그대로 확정 리스트(항상 전체 공개)에 올리는 것은
   다른 문제다. 후자를 허용하면 「지도에 올리기」를 거치지 않고 비공개 AI 후보가 공개로
   새는 셈이라 최종기획안 7절 가드레일 1을 어긴다. `resource.kind`에는 visibility 정보가 없어
   authz 레이어(permissions 필드)에서는 이 판정이 불가능하므로, **`shortlist/loaders.py::
   load_pin_for_confirm`이 pins 레이어에서 `visibility=="private"`이면 `AI_PIN_PRIVATE`로
   막는다** — permissions 객체가 아니라 요청 처리 자체를 거부하는 방식으로 정본 확정.

세 규칙 모두 코드와 이 문서 사이에 더 이상 갭이 없다.
