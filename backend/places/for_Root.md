# places → 루트 보고 (#34a 실시간 연결 시험)

작성: 2026-09-30 · 범위: #53 코멘트 "A. 실시간 연결 시험" · 영구 저장 없음(B는 미착수)

## 1. 한 줄 상태

3개 어댑터 + 폴백 + pins/recommend real 슬롯 구현·단위 테스트 완료(`backend` 전체 666 passed, 3 skipped=live).
`PLACES_MODE=real`로 서버 기동 시 3개 슬롯이 real로 채워지는 것도 테스트로 고정했다.
**단, 실제 API 호출 관찰은 못 했다 — 이 클론의 `backend/.env`에 지도 API 키가 하나도 없다**(5개 설정값 전부 빈 값 확인).
아래 3절의 관찰 항목은 전부 "미관찰"이며, 키를 넣고 `python -m pytest -m live places -s`를 돌리면 채울 수 있다.

## 2. 구현 구조 (`backend/places/`)

| 파일 | 역할 |
|---|---|
| `sources/base.py` | `RawPlace`, `PlaceSource` 프로토콜, 같은 장소 판정(이름+200m) |
| `sources/kakao.py` | 카테고리 검색(FD6/CE7/AD5/AT4, 반경 ≤20km, 최대 2페이지), 키워드 검색으로 전화 보완 |
| `sources/naver.py` | 지역 검색(키워드만·최대 5건). nearby는 "카테고리 키워드 검색 후 반경 필터"뿐이라 약하다 |
| `sources/google.py` | searchNearby(풀) / searchText(보완). FieldMask 필수, 재시도 없음, 프로세스당 호출 상한 |
| `fallback.py` | 순수 판단: 검색 폴백(카카오→네이버→구글), 보완(비어 있는 필드만 하위 소스에 묻는다) |
| `http.py` | 타임아웃 3초·재시도 1회(타임아웃/429/5xx만)·소스별 호출 횟수 로그(`places.call ...`) |
| `cache.py` | 메모리 TTL 캐시(`PLACES_CACHE_TTL_S`, 0이면 끔). DB 저장 없음 |
| `service.py`, `api.py` | 게이트웨이 본체와 공개 접점(`search_nearby`, `get_raw_facts`, `resolve_place`, `call_counts`) |

- **검색 풀은 카카오 한 번**(폴백 시 다음 소스). **가격·평점·영업시간 보완은 `get_raw_facts`에서 장소당 1회, 구글로만** 한다 — 풀 검색에는 과금 큰 필드를 안 붙인다.
- 보완 시 이미 채워진 필드는 다시 묻지 않고, 하위 소스가 못 주는 필드뿐이면 호출 자체를 안 한다(테스트로 고정).
- 구글 안전장치: FieldMask에 필요한 그룹만, `priceRange`(가격 숫자)는 요청하지 않고 `priceLevel` 열거값만, 재시도 0, `PLACES_GOOGLE_MAX_CALLS`(기본 100) 초과 시 호출 차단, 장소당 보완 시도 1회(못 채워도 반복 안 함).
- `place_id`는 `"<소스>:<소스 내 id>"`(예: `kakao:1234`, `google:ChIJ…`). 네이버는 id가 없어 이름+좌표 해시(12자)를 쓴다 — **#33 중복 판정 기준과 맞물리는 부분이라 확정이 필요하다**(같은 가게가 소스가 달라 다른 place_id를 갖는다).
- `get_raw_facts`가 돌려주는 키: `name, category, address, place_url, phone, rating, rating_count, price_level(열거값), opening_hours(요일 문자열)` — 값이 있는 것만. `fact_key`·`unknown_policy`는 건드리지 않았다.

### 설정 (모두 `common/settings.py`, `.env.example`에 주석 처리로 안내)
`KAKAO_REST_API_KEY`(없으면 `KAKAO_CLIENT_ID`), `NAVER_SEARCH_CLIENT_ID/SECRET`, `GOOGLE_PLACES_API_KEY`(→ PR #173),
`PLACES_SOURCES`(순서=폴백 순서, 예 `kakao,naver`로 구글 차단), `PLACES_CACHE_TTL_S`, `PLACES_HTTP_TIMEOUT_S`, `PLACES_HTTP_RETRIES`, `PLACES_GOOGLE_MAX_CALLS`.

## 3. 관찰 기록 — 미관찰 (키 필요)

키를 넣은 뒤 채울 표. 값은 **실제 호출 결과만** 적고, 약관 문구는 원문 URL·조항 번호와 함께 인용한다(#53 체크리스트와 같은 기준).

| 항목 | 카카오 로컬 | 네이버 지역검색 | 구글 Places(New) |
|---|---|---|---|
| 응답 필드(실측) | 미관찰 | 미관찰 | 미관찰 |
| 일일 한도/QPS(콘솔·헤더 실측) | 미관찰 | 미관찰 | 미관찰 |
| 과금(SKU, 콘솔 실측) | 미관찰 | 미관찰 | 미관찰 |
| 이용약관 저장·캐시 조항 원문 | 미확인 | 미확인 | 미확인 |

코드를 짜면서 세운 **가정(검증 안 됨)** — 실호출로 확인해야 한다:
- 카카오는 좌표·주소·전화·`place_url`은 주지만 가격·평점·영업시간은 안 준다.
- 네이버 지역검색은 좌표 검색이 없고 결과 5건 상한이라 nearby 풀로는 사실상 못 쓴다. 좌표는 경위도×1e7 정수 문자열로 온다고 가정하고 파싱한다.
- 구글은 FieldMask에 rating/priceLevel/regularOpeningHours/nationalPhoneNumber를 넣으면 상위 SKU로 과금된다고 알고 있다(검증 필요).
- 위 값들은 이 문서에서 결정 근거로 쓰지 말 것 — 관찰 전이다.

## 4. 루트에 요청·확인할 것

1. **키 발급/주입**: 시험을 하려면 이 클론 `backend/.env`에 키가 필요하다(커밋 금지). 넣은 뒤 live 테스트를 돌려 3절을 채우겠다.
2. **모듈 의존 표 갱신**: `docs/architecture.md` 1절 의존 열에 `pins → places`, `recommend → places`가 실제 import로 생겼다(둘 다 `places.api`/`places.schemas`만 사용, deps.py 어댑터 안에서). places 자체는 pins/recommend 타입을 import하지 않는다 — 그래서 변환용 어댑터(`RealPlaceGateway` 등)가 각 모듈 `deps.py`에 있다.
3. **`PinDraft`에 `place_name`이 없다**: 이름 검색으로 핀을 만드는 흐름(place_id 없이 이름만 오는 경우)은 지금 resolve가 처리할 수 없다(`place_id` 또는 lat/lng 필요, 없으면 422). 필요하면 `pins/ports.py`(루트/pins 소관)에 필드를 추가해야 한다.
4. **캐시를 끄면**(`PLACES_CACHE_TTL_S=0`) `get_raw_facts`는 항상 `{}`이고 `resolve`는 좌표가 요청에 있어야 한다 — 저장을 안 하니 "직전 검색 결과"를 기억할 곳이 없다. 다중 인스턴스(Cloud Run) 배포 시에는 검색과 라벨링이 다른 인스턴스로 가면 캐시 미스가 난다 — 공개 배포 전에 #53 결정과 함께 다시 봐야 한다.
5. `GET /places/search` 같은 FE용 검색 엔드포인트는 `docs/api-spec.yaml`에 없다. 지금 FE가 `place_id`를 어디서 얻는지는 스펙 밖이다(스펙은 건드리지 않았다).

## 5. 하지 않은 것
- `place_facts` 쓰기·차원압축 파이프라인, DB 스키마/마이그레이션 변경(#34b, #53 이후)
- `docs/`·`최종기획안.md` 수정
- 이슈 #34 "실제 소요" 기입 — 이 이슈는 B(영구 수집)가 남아 있어 끝난 게 아니다. A 파트 실제 소요는 PR 머지 후 코멘트로 남기는 게 맞다고 본다.
