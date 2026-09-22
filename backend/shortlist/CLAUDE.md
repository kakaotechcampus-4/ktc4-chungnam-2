# backend/shortlist

루트 문서를 먼저 읽는다: `/CLAUDE.md`, `backend/CLAUDE.md`(백엔드 공통), `docs/api-spec.yaml`(`shortlist` 태그), `docs/data-model.md`(`shortlist_items`).

## 책임

- 확정 리스트 추가/제외 — 구성원 누구나 (5-3, `authz`의 `member.actions`에 이미 선언됨)
- 동선 계산(5-10) — **최근접 이웃 기반 순수 계산, 모델을 쓰지 않는다**
- 동선 재계산은 `POST /maps/{mapId}/route`(「동선 짜주기」) **수동 트리거로만** 일어난다
  (`docs/api-spec.yaml`, `docs/events.md:30` — 확정 리스트 변경만으로는 `route.recalculated`를
  발행하지 않는다). 이전 버전의 이 문서는 "확정 리스트 변경 시 즉시 재계산"이라고 서술했으나
  `docs/api-spec.yaml`이 정본이라 여기를 그 기준으로 고쳤다(mentor-review-plan.md PR #71
  멘토 리뷰 대응, for_Root.md 참고).

## 왜 "AI 동선 짜주기"가 아닌가

기획안 5-10: "순수 계산이다. 모델을 쓰지 않는다. 모델 호출은 여전히 2곳(현재 3곳)뿐이다." 이 모듈에서 LLM을 호출하는 코드를 짜면 안 된다 — `llm` 모듈에 의존하지 않는 유일한 로직 모듈이 이곳이다.

## 넘지 말 것

- `visit_order` 수동 정렬은 `docs/data-model.md`("9/4 회의로 해결된 것")에서 허용으로 이미
  확정됐다 — 동선(routes 테이블, #103)과는 무관한 별개 컬럼이라 자동 계산과 충돌하지 않는다.
  `PUT /maps/{mapId}/shortlist/order` 자체의 구현은 별도 이슈.
- ~~지역 클러스터링은 recommend의 5-6-1 로직을 재사용한다~~ — #103에서 루트가 "지역 클러스터링
  기준(거리 임계값 등)은 구현하면서 정하되 근거를 PR에 남겨라"고 위임해 재검토했다. recommend는
  아직 이런 클러스터링 유틸이 없고, recommend의 문제(사람이 선언한 반경 원들의 교집합/합집합)와
  이 모듈의 문제(이미 확정된 핀들의 지리적 근접도)는 서로 다른 계산이라 공용화 대상이 아니라고
  판단했다 — `shortlist/routing.py`에 거리 임계값 기반 단일 연결 클러스터링을 자체 구현
  (`for_Root.md` 근거 참고). 이후 recommend 쪽에도 비슷한 유틸이 필요해지면 그때 공용화를
  재검토한다.

## 완료 정의

- `/maps/{id}/shortlist` CRUD, `/maps/{id}/route` 구현 + 단위 테스트
- 여러 지역에 걸친 확정 핀 입력 시 지역별로 별도 동선이 나오는지 테스트 (8km 이상 떨어진 두 클러스터 케이스)
- 확정 리스트 변경 후 `POST /maps/{mapId}/route`를 다시 호출하면 최신 상태로 재계산되는지 테스트
  (자동 재계산이 아니라 수동 트리거 — 위 "책임" 절 정정 참고)

## 코드 품질

`docs/code-quality.md` 참고. 모델을 쓰지 않는 모듈이라는 경계(위 "왜 AI 동선 짜주기가 아닌가")를 지켰는지가 스코프 리뷰의 핵심이다.
