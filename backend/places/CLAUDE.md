# backend/places

루트 문서를 먼저 읽는다: `/CLAUDE.md`, `backend/CLAUDE.md`(백엔드 공통), `docs/architecture.md` 2절(3층 데이터 모델), `docs/data-model.md`(`places`, `place_facts`), `docs/constraints.md`.

## 책임

- **`PlaceSource` 어댑터 구현 — v1부터 `KakaoPlaceSource`·`NaverPlaceSource`·`GooglePlaceSource` 3개 전부 실사용**
  (2026-09-07 결정, 이슈 #14 하위 결정 갱신 — 상세는 이슈 코멘트 참고).
  소스 우선순위(비용 순): ① 카카오 로컬 API로 좌표·기본정보(층1)를 채운다 → ② 카카오가 안
  주는 값(가격·평점·영업시간)은 **네이버 지역 검색 API**(무료 티어 검색 API, 유료 지도 SDK와는
  다른 상품이니 혼동 주의)로 먼저 보완한다 → ③ 그래도 없으면 **Google Places API**로 최종
  보완한다(Enterprise SKU 과금 발생 — 호출량을 최소화한다).
- 층2 반구조화 데이터 수집·**차원 압축** 파이프라인 (예: 메뉴 가격 스크래핑 → `price_bucket`)
- `place_facts` 조회·저장 API (내부용 — `recommend`가 호출)

## 왜 "카카오 API가 안 줘서" 방식으로 짜면 안 되는가

`docs/architecture.md` 2절을 반드시 읽는다. 요지: 어떤 API를 쓰든 재료·매운맛·붐빔 같은 층3 값은 아무도 안 준다. "이 API가 뭘 주는가"가 아니라 "우리가 채워야 할 값이 무엇인가"(`docs/constraints.md`의 `fact_key` 목록)에서 거꾸로 설계한다.

## 넘지 말 것

- **원본 가격 숫자를 저장하지 않는다.** `price_bucket`처럼 압축된 값만 `place_facts`에 쓴다 (architecture.md 2절 — 이게 D2 결정의 법적 근거다).
- `place_facts`를 TTL 캐시로 취급하지 않는다. 만료 삭제 로직을 넣지 말 것 — 버전 갱신(`labeled_at` 최신화)만 한다.
- `docs/constraints.md`의 `fact_key` 목록·`unknown_policy`를 이 모듈에서 바꾸지 않는다. 새 조건이 필요하면 루트에 보고.
- **3개 소스 실제 수집을 시작하기 전에 각 API 이용약관의 "결과 캐싱/영구저장" 조항을 확인한다.**
  이슈 #11 D안에서 "수집 범위·방식의 윤리·약관 검토 필요"로 남겨둔 항목이 아직 미해결이다 —
  진행 상황은 이슈 #53 참고. 특히 Google Places API는 필드별로 저장 허용 기간이 다르게 걸려
  있는 경우가 많다. 확인 전엔 `source_id`(자사 place_id) 외의 원본 응답 필드를 영구 저장하지
  않는다.

## 완료 정의

- `KakaoPlaceSource`·`NaverPlaceSource`·`GooglePlaceSource` 3개 구현체 + 단위 테스트(목 응답 기반)
- 소스 우선순위·폴백 로직(카카오→네이버→구글) 단위 테스트 — 상위 소스가 필드를 채우면 하위
  소스는 그 필드를 다시 조회하지 않는지 확인
- 층2 압축 로직 단위 테스트(가격 목록 → 버킷 매핑 케이스)
- `place_facts` 조회 시 `confidence=unknown`인 값에 대해 상위 모듈이 `docs/constraints.md`의 정책을 적용할 수 있도록 필드가 그대로 노출되는지 테스트

## 코드 품질

`docs/code-quality.md` 참고. 원본 가격 등 압축 전 데이터가 실수로 저장/노출되지 않는지가 이 모듈의 리뷰 1순위다.
