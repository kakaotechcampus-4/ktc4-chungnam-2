# 루트 리뷰 가이드 — backend/authz (#36)

`backend/pins/for_Root.md`(#16·#17)와 같은 형식.

## 구현 범위

- `can(user, action, resource) -> bool` 판정 엔진 + `permissions_for(user, resource) -> Permissions`
  주입 유틸(`authz/core.py`)
- `docs/permissions.md`의 역할 선언을 그대로 옮긴 `authz/policy.py`
- `maps`(#19) 전까지 쓰는 포트+개발용 스텁(`authz/ports.py`, `authz/deps.py`) — `backend/pins`가
  세운 패턴 그대로 재사용
- 테스트 46개 통과(`pytest authz/tests`), 전부 순수 단위 테스트 — DB·docker-compose 불필요
- `docs/permissions.md` "15-1 표와의 매핑" **5개 행 전부** 커버(`test_mapping_15_1.py`)
- 드리프트 테스트(`test_policy_drift.py`) — `docs/permissions.md`·`docs/api-spec.yaml`을 실제로
  파싱해서 `policy.py`·`schemas.py`와 대조. 일부러 액션 하나를 빼서 실제로 실패하는 것 확인 후 복구.
- `backend/pins/**`는 손대지 않았다(PR #52 미머지). `backend/main.py`도 손대지 않았다(authz는
  HTTP 표면이 없다 — 아래 "루트 확인·결정 필요" 5항 참고).

## 꼭 읽어야 할 것 (판단이 들어간 곳)

1. **이 파일 아래 "루트 확인·결정 필요" 항목들.**
2. **`authz/core.py`의 `can()`** — 판정 순서가 곧 정책이다. 특히:
   - 0단계: `Principal.map_id != Resource.map_id`면 `ValueError`. 이건 권한 거부가 아니라 호출부
     배선 버그로 취급했다 — 지도 A에서 뽑은 역할로 지도 B의 리소스를 판정하는 교차 지도 권한
     상승을 조용히 통과시키지 않기 위함.
   - 1단계: 비구성원은 **자신이 작성자여도** 전부 False. author는 member 위에 얹히는 범위지
     독립 역할이 아니다(`permissions.md` 25·41행).
   - 2단계: `policy.py`의 `ACTION_RESOURCE_TYPES` 파생 표로 액션-리소스 종류 결합을 확인한다.
     이게 없으면 `can(member, "recommend.publish", 핀리소스)`처럼 액션과 무관한 리소스 종류에
     대한 질문이 조용히 True로 새는 타입 혼동이 생긴다.
3. **`authz/policy.py`의 `AUTHOR_CONSTRAINED_ACTIONS`·`ACTION_RESOURCE_TYPES`** — 둘 다
   `docs/permissions.md`에 없는 파생 규칙이다. 정본을 **좁히기만** 하지만(정본에 없는 액션을
   새로 허용하지 않는다), 정본 승격 여부는 루트 판단.
4. **`authz/core.py::permissions_for`의 pin 행이 `pins/core.py::pin_permissions`와 동등한지** —
   `test_permissions.py::test_pin_permissions_matches_pins_module`가 6조합
   (`kind × is_member`)을 `model_dump(exclude_none=True)` dict 비교로 고정해뒀다. #56에서
   pins가 이 모듈로 갈아탈 때 FE 응답이 바뀌지 않는다는 안전망.

## 가볍게 훑거나 생략해도 되는 것

- `authz/schemas.py` — `api-spec.yaml`의 `Permissions`와 1:1, 필드 6개 전부 optional
- `authz/ports.py`·`authz/deps.py` — `pins/ports.py`·`deps.py`와 같은 패턴, `AllowAllMembership`도
  이름 그대로 "아직 검증 안 함" 스텁
- `authz/service.py` — 게이트웨이 호출 하나뿐인 얇은 셸
- `authz/tests/test_can.py`, `test_mapping_15_1.py` — 46개 테스트 통과로 갈음

## 루트 확인·결정 필요

**계약 갭**
1. `backend/pins/core.py::pin_permissions`가 권한 로직을 자기 모듈 안에 하드코딩 중이다.
   `authz/CLAUDE.md`가 명시적으로 금지한 형태("다른 모듈에서 권한 로직을 재구현하는 순간 이
   모듈을 둔 의미가 없어진다")지만, 이번엔 PR #52 충돌 회피로 `pins`를 손대지 않았다. #56에서
   이관 전까지 같은 규칙이 두 곳에 산다.
2. `Permissions` pydantic 모델이 `pins/schemas.py`에도 있다(`Pin`·`EvidenceLine`·`ShortlistItem`이
   공유하는 스키마인데 pins 소유). authz로 옮기는 게 맞다 — #56 범위로 남겨둔다.
3. `recommend.publish`의 author 제약("candidate.requested_by 본인만")이 `permissions.md`의
   액션 표가 아니라 23행 주석에만 있다. 코드에서는 `AUTHOR_CONSTRAINED_ACTIONS`로 격리했지만
   정본 표로 승격하는 게 나아 보인다.
4. `authz/CLAUDE.md` 완료 정의는 "15-1 표와의 매핑 절 **4개** 행"이라 적혀 있지만 실제
   `docs/permissions.md`의 표는 **5행**이다(반경 조정 행이 별도로 있음). 문서 쪽 수정 필요 —
   코드는 5행 전부 커버했다.
5. `Permissions`의 6개 boolean이 `permissions.md`에 선언된 액션 전부를 덮지 못한다.
   대응 필드가 없는 액션: `pin.create`, `evidence.add`, `recommend.request`, `recommend.publish`,
   `candidate.view_private`, `member.kick`, `map.settings.edit`. FE가 이 액션들의 버튼
   disabled를 무엇으로 판단하는지 불명확 — `can()`을 호출하는 별도 채널이 필요한지 확인 필요.
6. `Candidate` 스키마(`api-spec.yaml`)에 `permissions` 필드가 없다 — "모든 리소스 응답에
   permissions" 원칙이 candidate에는 적용되지 않는다. 현재는 `AI_PIN_PRIVATE` 404로만 막힌다.
   `authz/core.py::permissions_for`도 `candidate`·`map`은 지원하지 않고 `ValueError`를 던진다
   (호출하면 무엇이 비었는지 바로 드러나게 하려는 의도 — `can()`만으로 판정은 가능하다).
7. 확정리스트 상태 게이팅(`kind == "확정"`일 때 add/remove 반전)이 `permissions.md`에 없다.
   권한이 아니라 상태 규칙이라 `can()`이 아니라 `permissions_for`에만 넣었다. `pins` 동작과
   맞추려고 그렇게 했지만 정본에 근거가 없다.
8. 확정 제외의 대상이 두 갈래다 — 실행은 `DELETE /shortlist/{itemId}`(`shortlist_item`)인데
   `Pin` 스키마에도 `can_remove_from_shortlist`가 있어 표시용 판정은 `pin` 기준으로도 필요하다.
   `authz/policy.py::ACTION_RESOURCE_TYPES`에서 `shortlist.remove`를 두 리소스 종류 모두에 열어
   뒀다. `shortlist_item`의 permissions 규칙 자체도 `shortlist`(#7)가 없어 추정으로 구현했다
   (`can_add_to_shortlist`는 항상 False — 이미 리스트에 있는 항목이라 "추가"가 의미 없다는 가정).
   #7 도착 시 재확인 필요.
9. `permissions.md`에 액션-리소스 종류 결합표가 없다 — `authz/policy.py::ACTION_RESOURCE_TYPES`가
   그 갭을 메운 파생 표다(정본을 좁히기만 함). 정본으로 승격할지 확인 필요.
10. `api-spec.yaml`에서 403(`Forbidden`)이 `PATCH /runs/{runId}/evidence` 한 오퍼레이션에만
    선언돼 있다. `FORBIDDEN`은 `docs/errors.md`의 일반 코드인데 다른 오퍼레이션엔 403 응답
    정의가 없다.

**부수 변경**
11. `backend/requirements.txt`에 `pyyaml==6.0.2` 한 줄 추가 — 드리프트 테스트가 `docs/permissions.md`·
    `docs/api-spec.yaml`을 실제로 파싱하는 데 쓴다. 공용 파일이라 여기 명시한다.

**환경 이슈 (authz와 무관, 참고용)**
12. 이 작업 중 확인한 것: 현재 개발 환경에 `geoalchemy2`가 설치돼 있지 않아 `backend/pins`의
    테스트·`main.py` import 자체가 이 환경에서 안 된다(`ModuleNotFoundError: geoalchemy2`).
    `authz`는 `geoalchemy2`에 의존하지 않아 영향받지 않지만, `backend/pins`·`main.py` 관련
    작업을 하려면 `pip install -r requirements.txt`가 실제로 다 깔렸는지 먼저 확인이 필요해 보인다.
