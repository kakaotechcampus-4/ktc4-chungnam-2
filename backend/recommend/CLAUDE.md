# backend/recommend

루트 문서를 먼저 읽는다: `/CLAUDE.md`, `backend/CLAUDE.md`(백엔드 공통), `docs/api-spec.yaml`(`recommend` 태그 전체), `docs/data-model.md`(`recommend_runs`, `evidence_lines`, `regions`, `candidates`, `exclusions`), `docs/constraints.md`.

## 책임

가장 넓은 모듈이다. 기획안 3절 에이전트 루프의 코드 담당 단계 전부.

- run 생성, 근거 조립(①②), 근거 토글/추가
- 지역 확인(5-6-1 signature 저장·무효화)
- 실격 필터 실행(③-a-2, `docs/constraints.md`를 그대로 순회)
- 선호 순위 결과 조립(③-b는 `llm` 호출 결과를 받아 정렬)
- 대안 반영(④) — 비공개 candidate 생성
- 게시(`/candidates/{id}/publish`) — `pins`에 공개 핀 생성 요청
- 반경 넓히기, 재시도(제외목록에 넣고 재실행), funnel 집계

## 하지 않는 것

- 모델 호출 자체 (→ `llm`). 이 모듈은 `llm`에 "이 근거들을 구조화해줘" / "이 후보들 순위 매겨줘"라고 요청만 하고 프롬프트를 직접 다루지 않는다.
- 장소 라벨링 (→ `places`/`seeding`). 캐시 히트/미스만 확인하고, 미스면 `seeding`의 온디맨드 폴백 경로를 호출한다.

## 넘지 말 것

- **`docs/constraints.md`의 `unknown_policy`를 그대로 적용한다.** 안전 조건이 unknown인데 통과시키는 코드를 짜면 최우선 성공지표(실격 위반율 0%)가 깨진다 — 이 부분은 반드시 계약 테스트로 고정한다.
- 5-6 실격 필터 순서(반경→영업종료→실격조건→중복제외→정렬)를 바꾸지 않는다. 순서가 깔때기 표시(funnel)의 의미를 결정한다.
- 재시도 3회 상한 집계 단위, N의 정의는 결정 이슈 미결 — 구현 전 루트 확인.

## 완료 정의

- `docs/api-spec.yaml` `recommend` 태그 엔드포인트 전체 구현 + 단위 테스트
- `docs/constraints.md` 표의 각 `fact_key`에 대해 `unknown_policy`대로 필터링되는지 개별 테스트 (안전 조건 unknown → 제외 확인이 최우선)
- 5-6-1 지역 겹침/안 겹침 케이스, "두 지역 각각 찾기" signature 재확인 흐름 테스트
- 「다시 추천 받기」 시 이전 후보가 `exclusions`에 들어가고 다음 실행에서 제외되는지 테스트

## 우선순위

`llm` 모듈의 프롬프트 품질을 기다리지 말고 **스텁 응답으로 먼저 오케스트레이션·API·이벤트를 전부 통합**한다. FE+BE 코어 루프 데모가 AI 품질보다 먼저다 — `contracts/mocks`가 이 스텁의 참고 모양이다.

## 코드 품질

`docs/code-quality.md` 참고. 이 모듈은 특히 도메인 규칙(`unknown_policy`, 가드레일) 준수가 스타일보다 훨씬 중요한 리뷰 대상이다.
