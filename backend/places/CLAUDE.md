# backend/places

루트 문서를 먼저 읽는다: `/CLAUDE.md`, `backend/CLAUDE.md`(백엔드 공통), `docs/architecture.md` 2절, `docs/data-model.md`(`places`, `place_facts`), `docs/constraints.md`.

## 결정 (2026-10-01, #53) — 먼저 읽을 것

**카카오 로컬 API 응답은 어떤 형태로도 저장·캐시하지 않고 LLM에 보내지 않는다.** 저장하는 장소 데이터(이름·좌표·라벨)는 전부 자체 DB에서 온다. 허용·불허 표는 `docs/architecture.md` 2절. 이 결정은 이전의 "3개 지도 API 전부 실사용"과 "메모리 캐시 허용"을 대체한다.

## 책임

- **자체 장소 DB(#189)**: 서울 인허가 공공데이터(음식점·카페, 폐업 제외)와 TourAPI(관광지)를 `places`에 적재, 데이터 담당의 라벨 파일을 `place_facts`에 적재(확인 못 한 값은 `unknown`), 이름 검색과 반경 검색. **스펙(`docs/api-spec.yaml`, `docs/data-model.md`)이 먼저 확정돼야 시작한다.**
- **카카오 실시간 검색(표시용)**: `KakaoPlaceSource`만 켠다(`PLACES_SOURCES=kakao`). 결과는 화면에 보여 주고 버린다. 카카오 장소 ID·`place_url`·매칭 확인 일자만 저장할 수 있다. 사용자가 검색 결과를 고를 때 **한 건씩** 같은 자체 DB 장소를 찾는다(#191).
- `place_facts` 조회 API(내부용 — `recommend`가 호출). 응답에 카카오 원자료를 싣지 않는다.

## 넘지 말 것

- **카카오 응답(좌표·이름·주소 포함)을 메모리·DB·로그 어디에도 남기지 않고 LLM·`recommend`로 넘기지 않는다.** 응답 속도용 캐시도 안 된다(#188에서 `TTLCache` 사용을 없앤다).
- **자체 DB 전체를 카카오로 일괄 조회해 ID를 매칭하지 않는다**(대량 호출 금지). 매칭은 사용자가 고를 때 한 건씩.
- 사용자가 카카오 지도 위에서 지정한 좌표는 저장하지 않는다(길게 누르기 규칙은 #191 결정 후).
- `NaverPlaceSource`·`GooglePlaceSource`는 코드에만 있고 켜지 않는다.
- 원본 숫자(가격·면적 등)를 저장하지 않는다(`spacious`처럼 압축된 값만 — architecture.md 2절. 가격대 `price_bucket`은 #423에서 뺐다). `place_facts`를 TTL 캐시로 취급하지 않는다.
- `docs/constraints.md`의 `fact_key` 목록·`unknown_policy`를 이 모듈에서 바꾸지 않는다. 새 조건이 필요하면 루트에 보고.
- 공공데이터 데이터셋별 이용허락 범위와 갱신 주기를 적재 전에 확인해 for_Root.md에 적는다.

## 완료 정의

- #188: 카카오 응답이 메모리·DB·LLM 어디에도 남거나 넘어가지 않는다는 테스트
- #189: 서울 음식점·카페·관광지가 이름·좌표를 가진 채 적재, 이름 검색·반경 검색 단위 테스트, 폐업 제외·좌표 변환·업태 대응 테스트
- `place_facts`의 `confidence=unknown`이 그대로 노출돼 상위 모듈이 `unknown_policy`를 적용할 수 있다

## 코드 품질

`docs/code-quality.md` 참고. 카카오 원자료가 실수로 저장·전달되지 않는지가 이 모듈의 리뷰 1순위다.
