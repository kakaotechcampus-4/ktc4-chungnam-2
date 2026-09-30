# places → 루트 보고 (#34a 실시간 연결 시험)

작성: 2026-09-30 · 범위: #53 코멘트 "A. 실시간 연결 시험" · 영구 저장 없음(B는 미착수)

## 1. 한 줄 상태

3개 어댑터 + 폴백 + pins/recommend real 슬롯 구현·단위 테스트 완료(`backend` 전체 666 passed, 3 skipped=live).
`PLACES_MODE=real`로 서버 기동 시 3개 슬롯이 real로 채워지는 것도 테스트로 고정했다.
**카카오는 2026-09-30 실호출 관찰을 마쳤다(3절). 네이버·구글은 v1에서 끄므로 미관찰.**

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

## 3. 관찰 기록 — 카카오 (2026-09-30 실호출)

v1은 카카오만(`PLACES_SOURCES=kakao`). 네이버·구글은 켤 때 같은 방식으로 관찰한다(아래 표는 미관찰 유지).
실호출은 성수동(37.5445, 127.0561) 기준 category 4회·keyword 1회·잘못된 키 1회, 총 6회 + `pytest -m live` 1회.

### 3-1. 실측 (직접 호출한 결과)

| 항목 | 관찰 |
|---|---|
| 응답 필드(문서 1건) | `id, place_name, category_name, category_group_code, category_group_name, phone, address_name, road_address_name, x(경도), y(위도), place_url, distance` — 12개. **가격·평점·영업시간·메뉴·사진 없음** |
| `phone` | 빈 문자열인 가게가 있다(어묵나라 `""`, 웅칼 `""`) — 전화 없음 ≠ 오류 |
| meta | `total_count`(반경 안 전체, 453) / `pageable_count`(실제 볼 수 있는 수, **45**) / `is_end` / `same_name` |
| 페이지 | 15건씩 3페이지 = **최대 45건**. 4페이지를 요청해도 400이 아니라 200 + `is_end=true` + 15건이 오는데, 3페이지와 같은 내용으로 보인다(첫 문서 distance 196) → 우리 코드는 `is_end`에서 멈추므로 중복 수집은 없다 |
| 반경 | 20000 초과 시 **400** `ValidationError: query.radius should be at most 20000` — 코드는 20000으로 자른다 |
| 잘못된 키 | **401** `AccessDeniedError: wrong appKey(x) format` |
| 응답 헤더 | `x-request-id`만 있고 **남은 쿼터·rate limit 헤더는 없다**(`ratelimit-*`, `x-ratelimit-*` 없음) → 코드에서 호출 횟수를 직접 세야 한다(`places.call` 로그) |
| 성능 | 호출당 대략 1초 미만(테스트 1건 1.3초, 2페이지 포함) — 타임아웃 3초로 충분 |
| 우리 어댑터 | 카테고리 검색 2페이지 30건 정상 파싱(`kakao:771811963` 등), 카테고리·주소·`place_url` 매핑 확인 |

### 3-2. 공식 문서 인용 (직접 호출로는 알 수 없는 것)

**주의: 아래는 WebFetch(요약 모델 경유)로 읽은 것이라 인용이 정확한지 사람이 원문 페이지에서 한 번 더 확인해야 한다. 결정 근거로 쓰기 전 확인 필수.**

| 항목 | 내용 | 출처 |
|---|---|---|
| 일 쿼터 | 키워드 검색 100,000건, 카테고리 검색 100,000건 | developers.kakao.com/docs/ko/getting-started/quota |
| 초당/분당 제한 | 문서에 명시 없음 | 같은 페이지 |
| 과금 | 같은 표에 **"2원/건"** 으로 나온다고 읽혔다 — 카카오 로컬이 유료인지 쿼터 초과분 과금인지 불명확하다. **가장 먼저 원문 확인이 필요한 항목** | 같은 페이지 |
| 파라미터 한도 | 페이지 1~45, 장소 검색 size 최대 15, radius 최대 20000(m) — 실측과 일치 | docs/ko/local/dev-guide |
| 저장·캐시 조항 | **제5조 제20호**: "앱에서 사용자 환경을 개선하기 위한 목적 외 다른 목적으로 카카오에서 받은 데이터를 캐시하거나 캐시 후 최신 데이터로 유지하지 않는 행위"(금지 행위 목록) | developers.kakao.com/terms/ko/site-policies |
| 복제·제공 조항 | **제5조 제30호**: "서비스 및 개발자센터를 이용하여 얻은 정보(예: 데이터, 비밀 키, 엑세스 토큰 등 포함)를 카카오의 사전 승낙 없이, 복사, 복제, 변경, 번역, 출판, 방송, 검색 엔진 또는 디렉터리에 입력 기타의 방법으로 사용하거나 이를 타인에게 제공하는 행위" | 같은 페이지 |
| 출처 표시 | 별도 조항을 찾지 못했다 | 같은 페이지 |

- #53 코멘트가 인용한 "제5조 23호·31호"와 이번에 읽힌 번호(20호·30호)가 다르다. 약관 개정으로 번호가 밀렸거나 요약 오류일 수 있다 — 원문 확인 시 같이 볼 것.
- 해석(내 의견, 결정 아님): 20호는 "사용자 환경 개선 목적이면 캐시는 허용"으로 읽히는 문구라, **현재의 메모리 TTL 캐시(검색 직후 라벨링 용도)는 이 조항과 충돌 가능성이 낮다.** 반면 영구 저장·`place_facts` 적재(B 파트)가 "사용자 환경 개선" 범위인지는 이 문구만으로 판단할 수 없다 — 카카오에 직접 문의가 필요하다(#53 체크리스트). 30호(복제·제공)는 서버에서 모은 데이터를 여러 사용자에게 재제공하는 것과 관련될 수 있다.

### 3-3. 네이버·구글 — 미관찰 (켤 때)

| 항목 | 네이버 지역검색 | 구글 Places(New) |
|---|---|---|
| 응답 필드·한도·과금·약관 | 미관찰 | 미관찰 |

코드를 짜며 세운 가정(검증 안 됨): 네이버는 좌표 검색이 없고 5건 상한이라 nearby 풀로 약하다 / 구글은 FieldMask에 rating·priceLevel·openingHours를 넣으면 상위 SKU로 과금된다. 결정 근거로 쓰지 말 것.

## 4. 루트에 요청·확인할 것

1. **카카오 과금 원문 확인(최우선)**: 3-2의 "2원/건"이 사실인지 사람이 quota 페이지 원문으로 확인해 달라 — 사실이면 30건 풀 검색 1회 = 2회 호출이라 비용 설계에 반영해야 한다.
2. **모듈 의존 표 갱신**: `docs/architecture.md` 1절 의존 열에 `pins → places`, `recommend → places`가 실제 import로 생겼다(둘 다 `places.api`/`places.schemas`만 사용, deps.py 어댑터 안에서). places 자체는 pins/recommend 타입을 import하지 않는다 — 그래서 변환용 어댑터(`RealPlaceGateway` 등)가 각 모듈 `deps.py`에 있다.
3. **`PinDraft`에 `place_name`이 없다**: 이름 검색으로 핀을 만드는 흐름(place_id 없이 이름만 오는 경우)은 지금 resolve가 처리할 수 없다(`place_id` 또는 lat/lng 필요, 없으면 422). 필요하면 `pins/ports.py`(루트/pins 소관)에 필드를 추가해야 한다.
4. **캐시를 끄면**(`PLACES_CACHE_TTL_S=0`) `get_raw_facts`는 항상 `{}`이고 `resolve`는 좌표가 요청에 있어야 한다 — 저장을 안 하니 "직전 검색 결과"를 기억할 곳이 없다. 다중 인스턴스(Cloud Run) 배포 시에는 검색과 라벨링이 다른 인스턴스로 가면 캐시 미스가 난다 — 공개 배포 전에 #53 결정과 함께 다시 봐야 한다.
5. `GET /places/search` 같은 FE용 검색 엔드포인트는 `docs/api-spec.yaml`에 없다. 지금 FE가 `place_id`를 어디서 얻는지는 스펙 밖이다(스펙은 건드리지 않았다).

## 5. 하지 않은 것
- `place_facts` 쓰기·차원압축 파이프라인, DB 스키마/마이그레이션 변경(#34b, #53 이후)
- `docs/`·`최종기획안.md` 수정
- 이슈 #34 "실제 소요" 기입 — 이 이슈는 B(영구 수집)가 남아 있어 끝난 게 아니다. A 파트 실제 소요는 PR 머지 후 코멘트로 남기는 게 맞다고 본다.
