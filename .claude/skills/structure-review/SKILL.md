---
name: structure-review
description: PR이나 브랜치가 건드린 범위에서 "같은 문제를 여러 방식으로 푼 곳"을 찾아 리팩토링을 제안하고, 건드린 모듈의 의존 구조를 mermaid 그림으로 정리한다. 머지 전에 팀이 구조를 한 번 보고 가게 하려는 용도. "/structure-review 214", "이 PR 구조 점검해줘", "머지 전에 중복된 방식 있는지 봐줘" 같은 요청에 쓴다. PR에 코멘트를 달지 않는다(요청받았을 때만).
---

# PR 구조 점검

세션이 나뉘거나 바뀌면 앞서 정한 방식이 이어지지 않아 같은 문제가 다른 방식으로 풀린다(멘토 리뷰의 "인지부채"). 이 스킬은 **PR이 만든 변화가 기존 방식과 어긋나는지**를 본다. 버그 찾기는 `/code-review`가 한다.

인자: PR 번호·브랜치·경로. 없으면 현재 브랜치의 develop 대비 diff.

## 순서

1. 범위를 정한다: `git diff origin/develop...<대상> --name-only`. 바뀐 모듈(`backend/<module>`, `frontend`, `contracts`, `docs`)을 묶는다.
2. 기계가 잡는 것부터 돌린다. 이미 있는 가드가 실패하면 구조 점검 전에 그것부터 보고한다.
   `pytest integration/test_import_rules.py integration/test_spec_route_coverage.py integration/test_response_contract.py`
3. 아래 "같은 문제를 푸는 방식" 표의 각 줄에 대해, 바뀐 파일이 **새 방식을 하나 더 만들었는지** 본다. 그냥 쓰기만 했으면 문제 아니다.
4. 찾은 것마다 근거(파일:줄), 기존 방식이 어디 있는지, 합치면 무엇이 줄어드는지를 쓴다. 확인 못 한 건 "불확실"로 표시한다.
5. 건드린 모듈과 그 사이 호출 방향을 mermaid로 그린다(아래 형식).
6. 결과를 사용자에게 보여 준다. PR 코멘트는 사용자가 요청할 때만 `gh pr comment`로 단다.

## 같은 문제를 푸는 방식 (한 곳이어야 하는 것)

| 문제 | 한 곳 | 이렇게 보이면 의심 |
|---|---|---|
| 권한·소유자 판정 | `authz` 정책 테이블 | 모듈 안의 `if user_id == ...`, 같은 판정이 정책 테이블과 `core.py` 양쪽에 |
| 카테고리 목록·속성 | `common/categories.py`(#223 이후) | `"음식점"`·`"숙소"` 리터럴 비교, enum 재정의 |
| 비공개 후보 / 공개 | `candidates.published_pin_id` | `visibility == "private"` 분기, 새 비공개 상태 컬럼 |
| 동네 묶기·거리·반경 | `common/geo.py` | 모듈 안의 거리·클러스터 함수 복사 |
| 외부 의존(LLM·장소·인증) | 그 모듈의 `api.py` + 호출 쪽 `ports.py` Gateway | 다른 모듈 `service.py`·`models.py` 직접 import, 모듈마다 다른 dev/real 선택 방식 |
| 에러 코드 | `docs/errors.md` ↔ `common/errors.py` | 카탈로그에 없는 문자열 코드 |
| fact_key 목록 | `docs/constraints.md` | 코드·프롬프트 안의 키 목록 복사본 |
| 응답 필드 | `docs/api-spec.yaml` | 스펙에 없는 필드를 라우터가 반환 |

찾는 방법 예: `grep -rn '"숙소"' backend --include=*.py | grep -v tests`, `grep -rn 'def .*cluster\|haversine' backend`, `grep -rn 'visibility' backend --include=*.py`.

## 그림 형식

```mermaid
flowchart LR
  recommend -->|api| pins
  recommend -->|api| places
  recommend -.->|service 직접(위반)| llm
```
- 실선은 `api`·`schemas` 경유, 점선+이유는 규칙 위반이나 예외. 이 PR이 새로 만든 선은 굵게(`==>`).

## 보고 형식

1. 한 줄 판정(새 방식을 만들었나 / 기존 방식을 따랐나)
2. 발견 표: 문제 · 근거(파일:줄) · 기존 방식 위치 · 제안(합치기) · 확신(확인함/불확실)
3. 구조 그림
4. 제안 우선순위: 지금 고칠 것 / 이슈로 남길 것 / 그대로 둘 것(이유)
