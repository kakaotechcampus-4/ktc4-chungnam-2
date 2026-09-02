# backend/places

루트 문서를 먼저 읽는다: `/CLAUDE.md`, `docs/architecture.md` 2절(3층 데이터 모델), `docs/data-model.md`(`places`, `place_facts`), `docs/constraints.md`.

## 책임

- `PlaceSource` 어댑터 구현 (최소 `KakaoPlaceSource`. `GooglePlaceSource`는 인터페이스만 맞춰두고 초기엔 미사용 — Enterprise SKU 비용 문제)
- 층2 반구조화 데이터 수집·**차원 압축** 파이프라인 (예: 메뉴 가격 스크래핑 → `price_bucket`)
- `place_facts` 조회·저장 API (내부용 — `recommend`가 호출)

## 왜 "카카오 API가 안 줘서" 방식으로 짜면 안 되는가

`docs/architecture.md` 2절을 반드시 읽는다. 요지: 어떤 API를 쓰든 재료·매운맛·붐빔 같은 층3 값은 아무도 안 준다. "이 API가 뭘 주는가"가 아니라 "우리가 채워야 할 값이 무엇인가"(`docs/constraints.md`의 `fact_key` 목록)에서 거꾸로 설계한다.

## 넘지 말 것

- **원본 가격 숫자를 저장하지 않는다.** `price_bucket`처럼 압축된 값만 `place_facts`에 쓴다 (architecture.md 2절 — 이게 D2 결정의 법적 근거다).
- `place_facts`를 TTL 캐시로 취급하지 않는다. 만료 삭제 로직을 넣지 말 것 — 버전 갱신(`labeled_at` 최신화)만 한다.
- `docs/constraints.md`의 `fact_key` 목록·`unknown_policy`를 이 모듈에서 바꾸지 않는다. 새 조건이 필요하면 루트에 보고.

## 완료 정의

- 최소 1개 `PlaceSource` 구현체 + 단위 테스트(목 응답 기반)
- 층2 압축 로직 단위 테스트(가격 목록 → 버킷 매핑 케이스)
- `place_facts` 조회 시 `confidence=unknown`인 값에 대해 상위 모듈이 `docs/constraints.md`의 정책을 적용할 수 있도록 필드가 그대로 노출되는지 테스트

## 코드 품질

`docs/code-quality.md` 참고. 원본 가격 등 압축 전 데이터가 실수로 저장/노출되지 않는지가 이 모듈의 리뷰 1순위다.
