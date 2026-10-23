# places → 루트 보고 (#34a 실시간 연결 시험)

작성: 2026-09-30 · 범위: #53 코멘트 "A. 실시간 연결 시험" · 영구 저장 없음(B는 미착수)

## 1. 한 줄 상태

3개 어댑터 + 폴백 + pins/recommend real 슬롯 구현·단위 테스트 완료(`backend` 전체 666 passed, 3 skipped=live).
`PLACES_MODE=real`로 서버 기동 시 3개 슬롯이 real로 채워지는 것도 테스트로 고정했다.
**카카오는 2026-09-30 실호출 관찰을 마쳤다(3절). 네이버는 v1에서 끄므로 미관찰. 구글 소스는 #423에서 지웠다.**

## 2. 구현 구조 (`backend/places/`)

| 파일 | 역할 |
|---|---|
| `sources/base.py` | `RawPlace`, `PlaceSource` 프로토콜, 같은 장소 판정(이름+200m) |
| `sources/kakao.py` | 카테고리 검색(FD6/CE7/AD5/AT4, 반경 ≤20km, 최대 2페이지), 키워드 검색으로 전화 보완 |
| `sources/naver.py` | 지역 검색(키워드만·최대 5건). nearby는 "카테고리 키워드 검색 후 반경 필터"뿐이라 약하다 |
| `fallback.py` | 순수 판단: 검색 폴백(카카오→네이버), 보완(비어 있는 필드만 하위 소스에 묻는다) |
| `http.py` | 타임아웃 3초·재시도 1회(타임아웃/429/5xx만)·소스별 호출 횟수 로그(`places.call ...`) |
| `cache.py` | 메모리 TTL 캐시(`PLACES_CACHE_TTL_S`, 0이면 끔). DB 저장 없음 |
| `service.py`, `api.py` | 게이트웨이 본체와 공개 접점(`search_nearby`, `get_raw_facts`, `resolve_place`, `call_counts`) |

- **검색 풀은 카카오 한 번**(폴백 시 다음 소스).
- 보완 시 이미 채워진 필드는 다시 묻지 않고, 하위 소스가 못 주는 필드뿐이면 호출 자체를 안 한다(테스트로 고정).
- `place_id`는 `"<소스>:<소스 내 id>"`(예: `kakao:1234`). 네이버는 id가 없어 이름+좌표 해시(12자)를 쓴다 — **#33 중복 판정 기준과 맞물리는 부분이라 확정이 필요하다**(같은 가게가 소스가 달라 다른 place_id를 갖는다).
- `get_raw_facts`는 #188 이후 항상 빈 값이다(지도 API 응답을 추천·모델로 넘기지 않는다). `fact_key`·`unknown_policy`는 건드리지 않았다.

### 설정 (모두 `common/settings.py`, `.env.example`에 주석 처리로 안내)
`KAKAO_REST_API_KEY`(없으면 `KAKAO_CLIENT_ID`), `NAVER_SEARCH_CLIENT_ID/SECRET`,
`PLACES_SOURCES`(순서=폴백 순서), `PLACES_HTTP_TIMEOUT_S`, `PLACES_HTTP_RETRIES`.

## 3. 관찰 기록 — 카카오 (2026-09-30 실호출)

v1은 카카오만(`PLACES_SOURCES=kakao`). 네이버는 켤 때 같은 방식으로 관찰한다(아래 표는 미관찰 유지).
실호출은 성수동(37.5445, 127.0561) 기준 category 4회·keyword 1회·잘못된 키 1회, 총 6회 + `pytest -m live` 1회.

### 3-1. 실측 (직접 호출한 결과)

| 항목 | 관찰 |
|---|---|
| 응답 필드(문서 1건) | `id, place_name, category_name, category_group_code, category_group_name, phone, address_name, road_address_name, x(경도), y(위도), place_url, distance` — 12개. **평점·영업시간·메뉴·사진 없음** |
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

### 3-3. 네이버 — 미관찰 (켤 때)

| 항목 | 네이버 지역검색 |
|---|---|
| 응답 필드·한도·과금·약관 | 미관찰 |

코드를 짜며 세운 가정(검증 안 됨): 네이버는 좌표 검색이 없고 5건 상한이라 nearby 풀로 약하다. 결정 근거로 쓰지 말 것.

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

---

# #180 GET /places/search 보고 (2026-09-30)

## 구현
- `places/router.py`(신설) + `main.py`에 `include_router` 한 줄. 로그인만 필요, 지도 구성원 여부 무관.
- 검증 → 호출 상한 → 검색 순서. 검증 위반(q 공백·50자 초과, lat/lng 한쪽만, 범위·limit 위반)은 422 `VALIDATION_ERROR`이고 **상한을 소비하지 않는다.**
- `KakaoPlaceSource.search_by_name`: keyword.json. 좌표가 있으면 `x,y`+`sort=distance`(반경 제한 없음), 없으면 관련도 순. `size=min(limit,15)`, 1페이지만 부른다(호출 1회/검색).
- 카테고리는 `category_group_code` 제안값(음식점/카페/숙소/관광지/기타), 이름은 `place_name`(100자 상한으로 자름 — 핀 생성 요청과 같은 상한), `place_source{provider, url=place_url}`.
- 0건은 `[]`. 이름 검색 가능한 소스가 하나도 성공하지 못하면(키 없음·장애·호출 상한) 503 `PLACES_UNAVAILABLE`. 소스 하나가 실패해도 다른 소스가 0건으로 성공하면 `[]`(503 아님).
- 결과는 기존 `TTLCache`에만 담는다(영구 저장 없음). `resolve`(source=search)는 캐시에 place_id가 있고 echo 좌표가 캐시 좌표와 200m 넘게 다르면 422로 거절, 캐시에 없으면(만료) 지금처럼 echo 좌표를 쓴다.
- `PLACES_MODE=dev`(기본)는 카카오를 부르지 않고 고정 샘플 5곳(이름 부분 일치, 거리순)을 돌려준다. `contracts/mocks/handlers/places.ts`의 seed와 같은 장소 — **둘 중 하나를 바꾸면 둘 다 바꿔야 한다.**
- 설정 `PLACES_SEARCH_PER_MIN`(기본 30, 0 이하면 끔): `common/settings.py`, `.env.example`.
- `NameSearchable` 프로토콜로 이름 검색 지원 소스만 고른다 — 네이버 코드는 건드리지 않았다(켤 때 `search_by_name`을 구현하면 폴백에 자동 참여).

## 한계·주의 (루트 확인)
1. **호출 상한은 인메모리**다: 프로세스 재시작 시 초기화되고, 인스턴스가 여러 개(Cloud Run 다중)면 인스턴스마다 따로 센다 — 실효 상한은 `분당 30 × 인스턴스 수`까지 늘 수 있다. 카카오 일 쿼터(100,000건)를 지키는 용도로는 충분하지만 엄밀한 전역 상한은 아니다. 공개 배포 전에 Redis(`REDIS_URL`은 이미 있다) 등으로 옮길지 결정이 필요하다.
2. 검색 응답 자체는 캐시하지 않는다(같은 검색어도 매번 카카오 1회). 결과 장소만 place_id 조회용으로 캐시한다. FE debounce와 사용자당 상한이 1차 방어다. 검색어 캐시가 필요하면 별도 결정.
3. 캐시 TTL이 지나 만료된 뒤의 `source=search` 핀 생성은 echo 좌표를 그대로 믿는다(요청 사양대로). `PLACES_CACHE_TTL_S=0`이면 좌표 대조가 사실상 꺼진다.
4. `source=search`이면서 `place_id`가 dev 샘플(`kakao:mock-*`)인 핀은 dev에서만 생긴다. real 전환 후 기존 dev 핀과 place_id 체계가 섞이지 않게 주의.
5. 핀 생성 요청의 `place_name`은 클라이언트가 보낸 값을 그대로 저장한다(캐시의 이름과 대조하지 않는다) — 스펙 범위 밖이라 손대지 않았다.

## 실측 (카카오 live, 성수동 좌표 기준 "성수 칼국수")
키워드 검색이 5건의 `place_name`·좌표를 돌려주는 것을 확인했다(`pytest -m live places -k by_name`, 1 passed). 응답 필드는 3-1절의 12개와 같다.

## 테스트
- `places/tests/test_name_search.py`(요청 모양·폴백·503·상한·resolve 대조·샘플), `integration/test_places_search.py`(검색→핀 생성 201·place_name 저장, 0건, 422 10종, 429(사용자별), 503 2종, 401, 비구성원 허용), `test_response_contract.py` 골든 패스에 검색 호출 추가, `KNOWN_MISSING`에서 `("get","/places/search")` 삭제.
- 통합 테스트에서 추가 클라이언트를 `with TestClient(...)`로 열면 lifespan이 한 번 더 열려 dispatcher 싱글턴 상태가 남아 `realtime/tests/test_shutdown.py`가 깨진다(전체 실행에서만 실패, 단독은 통과). `with` 없이 쓰는 기존 패턴을 따랐다.
- `PINGO_TEST_DB=pingo_test_places python -m pytest` → 819 passed, 6 deselected(live), 실패 0.

---

# #188 카카오 응답 캐시 제거·LLM 경로 차단 (2026-10-01)

근거: #53 결정 — 카카오 응답은 저장·캐시하지 않고 외부 LLM으로 보내지 않는다.

## 바뀐 것
- `places/cache.py`(`TTLCache`) 삭제. `PlaceService`는 소스 목록 말고 어떤 상태도 갖지 않는다(`vars(svc) == {"_sources"}`를 테스트로 고정).
- `get_raw_facts`는 **항상 `{}`**. recommend→llm 경로에 지도 API 원자료가 닿지 않는다 — 빈 값이면 `llm.label_place`가 전부 unknown으로 응답하고 recommend가 `unknown_policy`로 처리한다. 보완용 `fallback.enrich`는 코드에 남지만 서비스가 부르지 않는다(네이버를 켤 때 다시 결정).
- `GET /places/search`·`search_nearby`는 결과를 응답으로만 돌려주고 즉시 버린다. `remember_and_convert` 제거(`to_result`로 대체). dev 샘플 검색은 `PlaceService`를 만들지도 않는다.
- `resolve`는 캐시를 쓰지 않는다. `source=search`도 echo된 `place_id`·`lat`·`lng`를 그대로 쓰고, 200m 캐시 대조는 없앴다. **좌표가 없으면 422**(이전에는 방금 검색한 캐시에서 채웠다).
- `PLACES_SOURCES` 기본값 `kakao` 하나(`common/settings.py`, `.env.example`). `PLACES_CACHE_TTL_S`(`places_cache_ttl_s`) 설정 삭제.

## 루트 확인
1. **`resolve`의 echo 신뢰는 #191(핀 찍기 규칙) 전의 임시 동작이다.** `source=search`로 온 `place_id`·좌표·이름을 서버가 어디와도 대조하지 않는다 — `coordinate` 경로가 이미 임의 좌표를 받으므로 위험이 늘지는 않지만, 클라이언트가 `kakao:<id>`에 엉뚱한 좌표를 붙여도 막지 못한다. #191에서 규칙을 정한 뒤 이 자리를 바꾼다.
2. **recommend의 후보 풀은 아직 `search_nearby`(카카오 실시간)에서 온다.** 후보 행에는 `place_id`·좌표만 저장되고(테스트로 확인), 라벨링 원자료는 비어 있어 라벨이 전부 unknown이 된다. 즉 실격 필터가 "모름" 정책만 타므로 추천 품질은 사실상 스텁 수준이다 — 카카오 응답을 LLM에 못 보내게 된 데 따른 결과다. 층2·3 라벨의 출처는 #53 후속 결정이 필요하다.
3. 이전 보고(위 #180 절)의 "캐시 만료 후 echo 신뢰", "`PLACES_CACHE_TTL_S=0`이면 대조 꺼짐" 항목은 이제 해당 없다.

## 테스트 (카카오 값이 어디에도 안 남는다는 고정)
- `places/tests/test_service.py`: 검색 직후·이름 검색 직후 `get_raw_facts == {}`, 보완 소스 호출 0회, 서비스 상태 없음, resolve 규칙(echo 그대로, 이전 검색과 다른 좌표도 통과, 좌표 없으면 422).
- `integration/test_places_no_kakao_leak.py`: 실제 `recommend.flows.execute_run`을 real 게이트웨이로 돌리고 `llm.label_place` 인자를 가로채 표식 값(이름·전화·주소·URL)이 없고 `{}`인지, 후보 행에도 표식이 없는지 확인. 검색 후 좌표 없는 핀 생성이 422임을 확인.
- `PINGO_TEST_DB=pingo_test_places python -m pytest` → 824 passed, 6 deselected(live), 실패 0.

---

# #189 PR 1 — 공개 함수 시그니처·대역 (2026-10-01)

계약 정본은 PR #196(`docs/places-api-contract`, 아직 미머지)의 `docs/architecture.md` "places 공개 함수 계약". 이 PR은 그 시그니처를 코드로 고정한다.

- `places/schemas.py`: `PlaceHint`, `PlaceMatch`, `PlaceInfo`, `PlaceRef`(기존), `FactLabel` 불변 dataclass.
- `places/api.py`: `match_place`, `record_kakao_match`, `pinnable_flags`, `get_places`, `search_nearby_own`, `get_facts` — **PR 1에서는 `NotImplementedError`**(구현은 PR 2). 기존 `search_by_name`·`get_raw_facts`·`search_nearby`·`resolve_place`는 그대로.
- `places/testing.py`: `FakePlaces` 메모리 대역(서울 가상 장소 8곳, 폐업 1곳, 라벨 3곳). `FakePlaces().install(monkeypatch)`로 `places.api`의 6개 함수를 바꿔 끼운다. 시그니처가 `api`와 같은지 테스트로 고정.
- `places/matching.py`(순수): 대역과 PR 2의 실제 구현이 **같은 매칭 규칙**을 쓰도록 먼저 넣었다. 규칙 — 반경 300m, 후보 수 상한 20(DB 조회 쪽 적용), 분류 일치, 이름 유사도 ≥ 0.8(괄호·공백·기호 제거 후 일치 / 한쪽 포함이고 길이 비율 ≥ 0.5 / 문자열 유사도), 이미 같은 카카오 ID가 기록된 장소는 이름이 달라도 그 장소(분류 일치 시), 이름 점수가 비슷한 다른 점포가 비슷한 거리(30m 이내 차이)에 있으면 모호하다고 보고 **None**.

## 계약에서 내가 정한 해석 (이견 있으면 알려 달라)
1. `get_facts`는 요청한 모든 `place_id`를 키로 돌려주고, 라벨이 없으면 빈 리스트다(없는 ID도 빈 리스트). 반대로 `get_places`는 없는 ID를 키에서 뺀다 — 계약 표 그대로.
2. `FactLabel.value`는 `Any`(boolean/문자열/None). `unknown`이면 `None`.
3. `match_place`가 돌려주는 `PlaceMatch`의 이름·좌표는 **자체 DB 값**이다(힌트 값을 되돌려주지 않는다).
4. `record_kakao_match`는 없는 `place_id`면 `KeyError`(대역 기준). 실제 구현은 PR 2에서 같은 동작으로 맞춘다.
5. 마이그레이션 번호: 지시문은 0016이지만 develop에 `0016_pins_spec_gaps.py`가 이미 있다 — PR 2는 그 다음 번호(0017 이상, 올리기 직전 develop 기준)로 만든다.

---

# #189 PR 2 — 자체 장소 DB 적재·공개 함수 구현 (2026-10-01)

PR 1(#197)에서 고정한 6개 공개 함수를 실제로 구현했다. 이 브랜치는 PR 1 위에 쌓여 있다(PR 1이 머지되면 diff에서 빠진다).

## 만든 것
- **마이그레이션 `0017_places_own_db`**: `places`(data-model.md 그대로), `place_facts`, GiST 인덱스 `idx_places_geom`. 지시문은 0016이었지만 `0016_pins_spec_gaps`가 이미 있다. 헤드가 `0015_recommend_gaps_158_146`(→0016 다음에 붙은 상태)이라 거기서 이었고, 스크래치 DB에서 `upgrade head` → `downgrade -1` → `upgrade head`를 확인했다(헤드 하나). 분류 enum은 pins의 `category`(5값)와 별개인 `place_category`(음식점·카페·관광지)로 뒀다.
- **적재 `python -m places.load {permit|tourapi|labels} --file ... [--dry-run]`**: 변환은 순수 함수(`places/ingest.py`), 파일·DB는 `places/load.py`. 건너뛴 행은 이유별 건수로 보고한다.
- **공개 함수 구현** (`places/api.py` → `repository.py` + `matching.py`).
- 의존성: `pyproj==3.6.1`(좌표 변환) → `requirements.txt`. CI는 Python 3.10에서 `pip install -r requirements.txt`를 하는데 3.10 manylinux wheel이 있음을 확인했다. 첫 CI 실행에서 설치를 한 번 더 봐 달라.

## 적재 규칙 (확인 필요한 가정은 표시)
| 항목 | 규칙 |
|---|---|
| 인허가 컬럼 | 관리번호·사업장명·영업상태명(·상세영업상태명)·업태구분명·도로명/소재지전체주소·소재지전화·좌표정보(X/Y). 헤더의 공백·BOM·대소문자·영문 별칭(MGTNO 등)을 허용. 인코딩은 utf-8-sig 후 cp949 |
| 좌표 | 기본 `EPSG:5174`(**가정 — 파일마다 다를 수 있다. `--crs`로 지정**). 값이 위경도 범위면 변환 없이 그대로. 변환 후 한국 범위(위도 33~39, 경도 124~132) 밖이면 건너뛰고, 대부분이 범위 밖이면 좌표계 경고를 낸다 |
| 서울만 | 주소가 "서울"로 시작. 주소가 없으면 건너뜀 |
| 폐업 | 영업상태가 폐업·휴업·취소/말소/만료/정지/중지면 **새로 넣지 않는다.** 이미 있던 장소가 폐업으로 바뀌어 오면 `status='closed'`로만 갱신(검색·매칭·추천에서 빠진다, 이미 핀이 가리키는 장소는 `get_places`로 계속 조회). 목록에 없는 상태("준비중" 등)는 건너뛰고 보고 |
| 업태 대응 | 카페: 카페·까페·커피숍·다방·전통찻집·라이브카페·제과점영업·아이스크림·키즈카페·커피전문점. 음식점: 한식·중식·일식·양식·분식·경양식·김밥(도시락)·패스트푸드·뷔페식·식육(숯불구이)·외국음식전문점·냉면집·횟집·복어취급·탕류(보신용)·통닭(치킨)·호프/통닭·기타·일반조리판매. **유흥·주점류(감성주점, 정종/대포집/소주방 등)는 일부러 뺐다.** 표에 없는 업태는 상위 10개를 경고로 보여 준다 — **데이터 담당과 대응표 확정이 필요하다** |
| TourAPI | `contenttypeid` 12(관광지)·14(문화시설)·38(쇼핑, 납품 파일은 시장만)을 받고 모두 `category=관광지`로 둔다(#379). 32(숙박)와 그 밖의 유형은 받지 않고 유형별 받은/건너뛴 수를 보고한다. 좌표가 서울 범위 밖이면 "서울 밖 좌표"로 건너뛴다. 서울(`areacode=1` 또는 주소 "서울")만. `mapx`=경도, `mapy`=위도(WGS84). **파일 입력(`--file`, API 응답 JSON 또는 item 배열)만 구현했다 — API를 직접 호출하는 수집기는 없다**(서비스키·엔드포인트 확인이 필요해서 보류) |
| 라벨 파일 | 형식은 architecture.md/data-model.md(#196) 그대로. 허용 `fact_key`는 **`docs/constraints.md` 표의 첫 열에서 읽는다**(코드에 목록을 복제하지 않는다. `is_open`·`within_radius`는 제외). `contains_*` 접두 재료 태그 허용 규칙은 #425에서 없앴다(표에 없는 키는 모두 건너뜀). 모르는 키·잘못된 값은 건너뛰고 건수 보고, 같은 키가 여럿이면 마지막 줄(경고), 멱등 upsert, 파일에 없는 키는 건드리지 않음. 값은 참/거짓만 받는다 — 원본 숫자는 저장되지 않는다. `source_layer`는 3. `unknown`이면 `value`는 SQL NULL(JSON null 아님) |
| 인허가×TourAPI 합치기 | **구현하지 않았다.** 인허가는 음식점·카페, TourAPI는 관광지라 분류가 겹치지 않는다. 같은 장소가 두 소스에 중복될 만한 경우(관광지로 분류된 카페 등)가 실데이터에서 보이면 그때 규칙을 정한다 |
| 재적재 | `kakao_*` 컬럼은 건드리지 않는다. `(source, source_id)`로 upsert |

## 매칭 규칙 (`places/matching.py`, `match_place`)
반경 300m(DB 조회 `ST_DWithin`) · 후보 수 상한 20(가까운 순) · 분류 일치 · 이름 유사도 ≥ 0.8(괄호·공백·기호 제거 후 같음 / 한쪽이 다른 쪽을 포함하고 길이 비율 ≥ 0.5 / 문자열 유사도) · 영업 중만 · 이미 같은 카카오 ID가 기록된 장소는 이름이 달라도 그 장소(분류 일치 시) · 이름이 거의 같은 다른 점포가 30m 이내 차이로 있으면 모호 → None. 숙소·기타는 DB를 보지 않고 None. 돌려주는 이름·좌표는 자체 DB 값이다.

## ⚠️ 계약 보강 요청 — `db` 키워드 인자
계약(#196)의 6개 함수에는 DB 세션이 없는데, `record_kakao_match`는 "핀 생성과 같은 트랜잭션"이어야 하고 다른 모듈의 api 함수(`pins.api` 등)는 전부 `db`를 받는다. 그래서 **선택 키워드 인자 `*, db: Session | None = None`을 6개 전부에 추가했다**(`FakePlaces`도 같은 시그니처 — 대역은 받기만 하고 무시한다). 호출 쪽은:
- `db=db`를 넘기면 그 요청 트랜잭션에 참여한다(커밋은 호출한 쪽이 한다). **pins의 `record_kakao_match`는 반드시 `db=db`로 부를 것.**
- 안 넘기면 places가 짧은 세션을 직접 열어 쓰고 닫는다. 읽기 전용 호출은 이걸로 충분하지만, 핀 생성 트랜잭션과 분리되고 호출마다 연결을 쓴다.
기존 호출(db 없이)은 그대로 동작하므로 PR 1 기준으로 개발 중인 pins·recommend 세션에는 영향이 없다. 계약 문서(architecture.md)에 이 인자를 반영해 달라.

## 데이터셋별 이용허락 범위·갱신 주기 — **확인 필요** (이 세션은 실제 파일·사이트를 확인하지 않았다)
| 데이터셋 | 용도 | 이용허락 범위 | 갱신 주기 |
|---|---|---|---|
| 지방행정 인허가 — 일반음식점 | 음식점 | 확인 필요 (공공데이터포털/LOCALDATA 해당 데이터셋의 이용허락범위·저작권 표시 의무) | 확인 필요 |
| 지방행정 인허가 — 휴게음식점 | 카페 | 확인 필요 | 확인 필요 |
| 한국관광공사 TourAPI (국문 관광정보) | 관광지 | 이슈 #189 본문 "저장 사용 허용 확인됨, 팀 결정" — 근거 문서·출처 표시 의무는 확인 필요 | 확인 필요 |
적재 스크립트는 멱등이라 갱신 주기가 정해지면 같은 명령을 주기적으로 다시 돌리면 된다(폐업 반영 포함).

## 테스트
`places/tests/` — `test_ingest.py`(폐업·좌표 변환·업태 대응·서울 필터·TourAPI·라벨, 가짜 픽스처 25행/8항목/17줄, 실제 상호 아님), `test_own_db.py`(적재 upsert·멱등·폐업 갱신·6개 함수·CLI, 실제 PostGIS), `test_own_db_contract.py`(FakePlaces ≡ api 시그니처, 대역 동작). 실제 공공데이터 파일은 저장소에 없다(`.gitignore`: `backend/data/`, `backend/places/data/`).
`PINGO_TEST_DB=pingo_test_places python -m pytest` → 933 passed, 6 deselected(live), 실패 0.

---

# #207 음식점 납품본 적재 (2026-10-02)

- `python -m places.load restaurants --file restaurant_seoul_curated.csv [--labels restaurant_seoul_curated_labels.json] [--exclude-bars] [--constraints …] [--dry-run]` — 장소 CSV와 라벨 JSON을 **같은 트랜잭션**으로 적재(dry-run이면 전부 롤백). 라벨만 다시 올릴 때는 `restaurant-labels --file …json`.
- 장소: `source='permit'`, `source_id=관리번호`, 분류는 전부 음식점, `status='open'`(영업 중인 곳만 받음), 좌표는 이미 WGS84라 변환하지 않고, 위·경도 중 하나라도 비면 건너뛴다. 업태가 빈 1곳은 음식점으로 넣고 경고한다.
- 라벨: `place_id`에서 `rest_`를 떼 `(permit, 관리번호)`로 장소를 찾고, `"true"/"false"`→boolean, `"unknown"`→`confidence=unknown`·value SQL NULL. `evidence`·`source`는 새 컬럼 `place_facts.evidence`·`label_source`(마이그레이션 `0019_place_facts_evidence`, down_revision `0018_pins_own_db_places`)에 저장. 같은 키 재적재는 근거까지 덮어쓴다. 허용 `fact_key`는 constraints.md에서 읽는다(미등록은 건너뛰고 키별 건수 보고).
- 유흥·주점류(정종/대포집/소주방 33곳, 감성주점 3곳)는 **루트 결정 대기**라 기본은 포함, `--exclude-bars`로 제외한다. 제외하면 그 장소의 라벨은 "장소 못 찾음"으로 센다.
- **`FactLabel`/`get_facts`는 `evidence`·`label_source`를 아직 내보내지 않는다.** 가드레일 5의 "이유·출처"에 쓰려면 계약(`FactLabel` 필드) 확장이 필요하다 — 루트 결정 필요(스키마만 먼저 저장해 뒀다).
- 성능: 라벨 18만 건 upsert가 이 PC에서 약 4분 걸렸다(청크 1,000건). 실제 적재는 한 번이라 그대로 뒀다.

## #238 검색 응답 `pinnable` + #248 `record_kakao_match` 첫 값 유지 (places 몫)

- **#238**: `GET /places/search`가 결과마다 `pinnable`을 채운다(`places.api.pinnable_flags`). 힌트는 결과의 `place_id`·이름·좌표·추정 분류로 만들고, **읽기만 한다**(카카오 ID 기록 없음). 힌트 N개를 **쿼리 한 번**(`repository.find_candidates_many`)으로 처리한다 — 힌트별로 가까운 순 20개와 같은 카카오 ID 장소를 뽑는 규칙은 `match_place`와 같고, 테스트가 둘의 결과가 같음을 확인한다. 자체 DB를 못 읽으면(`SQLAlchemyError`) 검색은 그대로 주고 `pinnable`만 생략한다(스펙상 optional). dev 모드도 같은 경로라 값을 낸다. `PlaceSearchResult.pinnable: bool | None` 추가.
- **#248 정책**: `record_kakao_match`는 **첫 값 유지**다. 장소에 카카오 ID가 이미 있고 다른 ID가 오면 아무것도 바꾸지 않는다. 같은 ID면 `kakao_matched_at`만 갱신한다. `FakePlaces`도 같다. (시그니처·예외는 그대로 — 없는 `place_id`는 `KeyError`.)
- **루트에 요청**: `docs/architecture.md`의 `record_kakao_match` 행("이미 있으면 덮어쓴다")을 "첫 값 유지, 같은 ID면 확인 일자만 갱신"으로 고쳐 주세요(스펙이라 이 모듈에서 바꾸지 않았다). `test_d7_*`의 xfail은 develop을 합친 뒤 이 PR에서 지웠다. `test_d21_*`는 pins 입력 검증(ID 형식·길이)과 함께 정리해야 한다.
- **#248의 pins 몫(미착수)**: 카카오 ID 형식 검증(`pins/core.py::kakao_place_url`)·`place_id`/`place_name` 길이 제한은 pins 담당이다. 이 PR은 places 정책만 한다.

---

# #499 인허가 커버리지 적재 (2026-10-13)

- **코드**: `ingest.PERMIT_ALIASES`에 선택 열 `분류`(카페/음식점)를 추가했다. 값이 둘 중 하나면 업태 대응표보다 우선하고, 열이 없거나 값이 이상하면 업태 대응표로 폴백한다. 좌표 없는 행은 `분류`가 있어도 건너뛴다. `places.load permit` 리포트에 "다른 분류로 이미 있음" 건수를 추가했다(음식점·카페 납품본 적재와 같은 줄). 테스트 `test_ingest.py`에 5건(우선·구제·폴백·대응표에도 없으면 건너뜀·좌표 없음).
- **명령**(윈도는 `PYTHONUTF8=1` — 없으면 리포트 출력에서 cp949 오류로 끝난다. 장소·라벨은 그 전에 커밋돼 있으니 출력만 실패한다): `python -m places.load permit --file permit_N.csv --encoding cp949`(3개) → `python -m places.load restaurant-labels --file permit_cover_labels.json`. 카카오 API는 부르지 않았고, 원본 파일은 커밋하지 않는다.
- **검증 DB**(pingo_demo 복사본 `pingo_verify499`) 결과 — 건수만:

| 파일 | 읽음 | 적재 대상 | 건너뜀(좌표 없음) | 신규 | 갱신 | 다른 분류로 이미 있음 |
|---|---|---|---|---|---|---|
| permit_1 | 73,697 | 72,930 | 767 | 72,900 | 12 | 18 |
| permit_2 | 2,939 | 2,907 | 32 | 2,848 | 53 | 6 |
| permit_3 | 16,303 | 16,075 | 228 | 15,879 | 176 | 20 |
| 합계 | 92,939 | 91,912 | 1,027 | 91,627 | 241 | 44 |

  README 시뮬레이션(91,912곳, 좌표 없음 1,027)과 일치. 신규 카페 23,147 / 음식점 68,480(시뮬레이션 23,387/68,525에서 기존 장소와 겹친 285행을 뺀 값).
- **라벨**: 읽음 720,654행 → upsert 713,186, 장소를 못 찾아 건너뜀 7,468(좌표 없어 적재 안 된 장소의 라벨). place_facts 256,698 → 968,996.
- **정예 보존**(적재 전 12,376곳 · 라벨 256,698행 스냅샷과 비교): 정예 장소의 category·kakao_place_id 변경 0, 정예 라벨 삭제 0, 값이 바뀐 라벨 1건(`franchise` unknown → known, 출처 franchise_brands).
- **README와 다른 점 — 확인 요청**: README는 "정예 파일과 관리번호가 겹치지 않는다"고 했지만 pingo_demo의 기존 장소와 **285행이 겹쳤다**(44행은 분류가 달라 건너뜀, 241행은 같은 분류라 갱신). 갱신된 241행은 좌표가 0.1m 이내로 반올림 차이만 났고 207행은 이름·주소 그대로, 34행은 **이름이 커버리지 파일의 정리된 이름으로 바뀌었다**. 기존 동작(같은 분류면 갱신)을 그대로 둔 결과다. 정예 이름을 지키려면 "이미 있는 (source, source_id)는 건드리지 않는다"로 바꿔야 하며, 이는 다른 납품본 재적재(갱신) 동작도 바꾸므로 결정을 요청한다.
- **로컬 pingo_demo 적재**: 백업 `C:\Users\user\Desktop\pingo_demo_before499.dump`(pg_dump -Fc). 되돌리기: `pg_restore --clean -d pingo_demo`. 적재 후 숫자는 아래.
  - 첫 시도에서 라벨 단계 중 Docker가 내려가 DB 연결이 끊겼다(장소 3파일은 커밋 완료, 라벨은 롤백). DB 복구 후 장소 104,003 · 라벨 256,698을 확인하고 라벨만 다시 적재해 성공했다.
  - pingo_demo 결과: 장소 104,003(음식점 80,323 / 카페 23,680, 신규 음식점 68,480 / 카페 23,147), 라벨 968,996(upsert 713,186, 못 찾아 건너뜀 7,468). 정예 category·kakao_place_id 변경 0, 정예 라벨 삭제 0, 값이 바뀐 라벨 1건(`franchise` unknown → known). 검증 DB와 같은 숫자다.

---

# #500 매처 주소 보조 매칭 + 매칭률 측정 (2026-10-13)

- **규칙**(`matching.py`, 순수 함수 — DB 구현과 `FakePlaces`가 같은 `pick_match`를 쓴다): `PlaceHint.address`(선택)와 `Candidate.address`(자체 DB)를 도로명(`성수이로 100`) 또는 지번(`성수동2가 300-1`)으로 줄여 비교한다(시·구·층·괄호·`로 12길` 띄어쓰기 정리). 결과는 같음 / 다름 / 비교 불가(한쪽이 없거나 도로명 vs 지번, 본번만 같고 한쪽에 부번이 없음).
  - **다름** → 그 후보는 다른 점포라 뺀다(같은 이름의 다른 지점을 거절). **비교 불가** → 이름 규칙 그대로(기존 동작).
  - **같음** + 이름 점수 0.5 이상 → 이름이 0.8에 못 미쳐도 같은 곳으로 본다. 단 이름만으로 충분한 후보(0.8↑)가 있으면 그쪽을 쓰고 이름이 모자란 후보는 보지 않는다.
  - 동명 점포 모호 거절은 유지하고, 주소가 같다고 확인된 후보가 이기면 모호하지 않다. 카카오 ID로 이미 짝지어진 장소는 주소를 보지 않는다. 분류가 같은 후보만 본다.
  - 주소는 비교에만 쓴다 — 저장·로깅하지 않는다(#53).
- **측정**: `python -m places.scripts.measure_match_rate [--queries 200] [--out rates.json]` — 지역×업종 200개 검색어(고정)로 장소 검색을 돌려 pinnable 비율을 [주소 보조 전/후]로 낸다. 출력은 건수·비율뿐이다. `KAKAO_REST_API_KEY`(환경변수)와 `PLACES_MODE=prod`가 필요하다.

  **측정 결과**(루트가 직접 측정, 같은 검색어 200개 × 2개 DB, 결과 2,999건, 같은 표본):

| DB | pinnable 주소 보조 전 | 주소 보조 후 | 주소로 새로 매칭 / 거절 |
|---|---|---|---|
| 적재 전(12,376곳) | 462/2999 (15.4%) | 493/2999 (16.4%) | 44 / 13 |
| 적재 후(104,003곳) | 1765/2999 (58.9%) | 1877/2999 (62.6%) | 120 / 8 |
| 정예 우선 적재 후(106,156곳, #507, 2026-10-15) | 1922/2999 (64.1%) | 2041/2999 (68.1%) | 132 / 13 |

  - 적재(#499)만으로 15.4% → 58.9%, 주소 보조로 +3.7%p(적재 후 기준). 순증은 새로 매칭에서 거절을 뺀 값이다(적재 전 +31, 적재 후 +112).
  - #507(정예 신규 3종·갱신본 적재) 뒤 같은 표본으로 다시 쟀다: 적재 전 15.4% → #499 58.9% → #507 64.1%, 주소 보조까지 켜면 **68.1%**(+4.0%p). 주소 보조 연결(`_fill_pinnable`, #550)이 병합되면 검색의 `pinnable`과 핀 생성 매칭이 같은 규칙으로 맞는다.
  - #507 적재는 커버리지 라벨 단계(`restaurant-labels`, 새 키 750개)만 pingo_demo에 반영되지 않았다(시스템 메모리 부족으로 중단). 장소·정예 라벨은 모두 반영됐고 보존 검증(삭제 0·카카오 ID 변경 0·status 변경 0·6곳 카페)을 통과했다.
  - 표본의 1/8이 "공원"(관광지, 인허가에 없음)이라 음식점·카페만의 비율은 더 높을 수 있다.
  - 이 숫자는 검색 라우터에 주소를 넘겼을 때의 값이다. 라우터 연결(아래 3번)은 스펙·pins가 머지되기 전에는 켜지 않는다.
- **루트에 요청 — 아직 켜지 않았다**: 검색 라우터(`_fill_pinnable`)는 주소를 넘기지 않는다. 지금 켜면 검색은 pinnable=true인데 핀 생성(`PinCreateSearch`에 주소가 없음)은 `PLACE_NOT_SUPPORTED`가 되어 어긋난다. 아래 3개를 **같은 시점에** 켜야 한다(순서: 1 → 2 → 3).

| # | 항목 | 담당 | 내용 |
|---|---|---|---|
| 1 | 스펙 `PinCreateSearch.address` | 루트 | `docs/api-spec.yaml`의 `PinCreateSearch`에 선택 필드 `address`(maxLength 200, 검색 결과의 address를 그대로 되돌려 보내는 **저장하지 않는 매칭 힌트**) 추가, `CHANGELOG-api.md`에 먼저 기록, `contracts/` 타입 재생성, FE에 통보. 필수가 아니라 선택이라 기존 호출은 그대로 동작한다 |
| 2 | pins 전달 | pins | `pins/schemas.py::PinCreateSearch`에 `address: str \| None = Field(default=None, max_length=200)`, `pins/service.py::_create_db_pin`이 `PlaceHint(..., address=req.address)`로 넘긴다. 주소는 저장·로깅하지 않는다(핀 행·감사 로그·예외 메시지에 넣지 않는다) |
| 3 | 검색 라우터 연결 | places | `places/router.py::_fill_pinnable`의 `PlaceHint`에 `r.address`를 추가한다(한 줄). 1·2가 머지된 뒤에 켠다 — 이 세션이 맡는다. 측정 스크립트는 이미 주소 있음/없음을 나눠 잰다 |

  FE는 핀 생성 요청에 검색 결과의 `address`를 함께 보내야 효과가 있다(보내지 않으면 지금과 같다 — 이름 규칙만 쓴다).


---

# #507 정예 우선 정책 + 인허가 갱신본(2)·정예 신규 3종 (2026-10-15)

- **정책(구현 완료, 테스트 `test_curated_first.py` 14개)**: `restaurants`·`cafes`·`tourapi`에 `--authoritative`를 주면 같은 (source, source_id)의 이름·분류·주소·좌표를 파일 값으로 갱신하고(분류가 달라도) 라벨도 파일 값이 덮는다. 카카오 ID·URL은 건드리지 않는다. `permit`(커버리지)은 이미 있는 장소의 이름·분류·좌표를 건드리지 않고 신규 행만 넣는다. `restaurant-labels`는 기본이 커버리지용 — 이미 있는 (장소, fact_key)는 건드리지 않고 없는 키만 넣는다(`--overwrite`면 덮는다). 옵션 없이 부르면 기존 동작(같은 분류면 갱신·다른 분류면 건너뜀)이다. 리포트에 갱신 중 이름·분류 바뀜 수와 "이미 있어 건드리지 않음"을 낸다.
- **적재 순서·명령**(결정 반영, 윈도는 `PYTHONUTF8=1`): `restaurants --file 음식점_1013/final_restaurant_places_hotspot.csv --labels seoul_restaurant_labels_hotspot.json --authoritative` → `cafes --file 카페_1013/cafe_seoul_curated.csv --labels cafe_seoul_curated_labels.json --authoritative` → `tourapi --file 관광지_1013/tourist_seoul_places.json --labels tourist_seoul_curated_labels.csv --authoritative` → `permit --file permit_data_2/permit_{1,2,3}.csv --encoding cp949` → `restaurant-labels --file permit_cover_labels.json`. **관광지 라벨은 JSON이 아니라 CSV를 쓴다** — JSON은 음식점 형식이 아니라 26,751행이 전부 "source/source_id 이상"으로 건너뛰어진다.
- **결정 ① (2026-10-15, 루트): 정예 카페·음식점 파일에 같은 관리번호 6곳은 카페로 둔다.** 나중에 적재한 쪽이 이기므로 순서를 음식점 → 카페로 했다. 복사본에서 6곳(애즈라이크·럭키서울·써머레인·그레인서울·훌리건커피·컨플릭트스토어 잠실점) 모두 카페로 남은 것을 SQL로 확인했다. 이름은 카페 파일 값이다(오리지널팬케이크하우스 → 컨플릭트스토어 잠실점, 훌리건 → 훌리건커피).
- **결정 ② (2026-10-15, 루트): 갱신본에서 빠진 657행은 그대로 둔다.** 삭제·status 변경 없이 보고만 한다(`closed` 0). 폐업·이탈 후보다.
- **충돌 규모(복사본 dry-run, 적재 전 상태 기준)**: 정예 음식점 1,570 → 신규 104·갱신 1,466(이름 바뀜 68·분류 바뀜 8; 옛 규칙은 8곳 건너뜀), 정예 카페 1,678 → 신규 1,329·갱신 349(이름 107·**분류 167**; 옛 규칙은 167곳 건너뜀), 관광지 723 전부 신규.
- **새 순서의 실제 적재 결과(복사본 `pingo_v507`, pingo_demo에서 새로 뜸)**: 음식점 신규 104·갱신 1,466(이름 68·분류 8) → 카페 신규 1,325·갱신 353(이름 110·분류 171; 겹침 6곳이 음식점에서 카페로 넘어가 이전 순서보다 신규 4·분류 4 차이) → 관광지 신규 723. 장소 106,156(음식점 80,265 · 카페 25,168 · 관광지 723), 라벨 968,996 → 1,027,876. 커버리지 장소 3파일은 읽음 101,514 → 신규 1·**이미 있어 건드리지 않음 100,425**·좌표 없음 1,088(갱신본 추가 9,232행이 전부 정예와 겹친다). 커버리지 라벨 807,484행 → 새 키 750·건드리지 않음 798,662·장소 없음 8,072.
- **보존 검증(SQL, 단계별 스냅샷 비교, 복사본)**: 커버리지 단계에서 장소 이름·분류·좌표·카카오 ID·상태 변경 0, 장소·라벨 삭제 0, 라벨 값·확신도·출처 변경 0. 정예 단계에서 카카오 ID 변경 0, 장소·라벨 삭제 0. 정예 파일이 의도대로 바꾼 것: 이름 175·분류 175·라벨 값 3,110.
- **참고**: 커버리지 갱신본에서 값이 바뀐 라벨(이미 있던 비정예 장소)은 "건드리지 않음"이라 반영되지 않는다. 유흥·주점류 업태가 정예에 카페 2·음식점 5행 포함(기존 "루트 결정 대기" 그대로).
- **pingo_demo 적재 — 중간에 멈췄다(미완료)**: 백업 `C:\Users\user\Desktop\pingo_demo_before507.dump`(pg_dump -Fc, 적재 직전 pingo_demo와 건수·최종 수정 시각이 같음을 확인. 되돌리기 `pg_restore --clean -d pingo_demo`). 같은 순서로 적재하던 중 시스템 메모리 부족으로 백그라운드 작업이 중단됐다. 중단 시점: 장소 단계(정예 3종 + 커버리지 3파일)는 끝나 장소 106,156으로 복사본과 같고, 정예 라벨까지 들어가 라벨 1,027,126이다. **커버리지 라벨(`restaurant-labels`) 단계만 반영되지 않았다**(복사본은 1,027,876, 750 차이). pingo_demo에 검증용 스냅샷 테이블 `snap0_*`·`snap1_*`이 남아 있다. 남은 일은 커버리지 라벨 한 단계이고, 끝난 뒤 보존 검증을 하고 스냅샷 테이블을 지운다.
- **복사본**: `pingo_v507`(적재·검증 완료본)은 비교용으로 남겨 두었다.

---

# #474 POST /places/from-link 구현 결과 (2026-10-15)

스펙(`LinkParseRequest`/`LinkParseResult`, `LINK_NOT_SUPPORTED`·`LINK_UNRESOLVED`)대로 구현했다. 스펙·`common/errors.py`는 바꾸지 않았다. parse-only — 핀·DB 쓰기·모델 호출 없음.

- **파일**: `linkparse.py`(순수 — 링크 읽기·도메인 허용목록), `linkfetch.py`(단축 링크 따라가기, SSRF 방어), `matching.pick_link_matches`(구글 짝 고르기), `api.parse_link`·`check_link_rate`·`own_places_near`·`own_places_by_kakao_id`, `router.py`(라우트), `schemas.LinkParseResult`, `testing.FakePlaces`에 대역 2개.
- **허용 링크**: 구글(`google.com`·`google.co.kr`의 `/maps…`, `maps.app.goo.gl`, `goo.gl`)과 카카오(`place.map.kakao.com/{id}`, `map.kakao.com/?itemId={id}`, `kko.to`). 네이버·인스타·블로그·그 밖은 422 `LINK_NOT_SUPPORTED`. 지도 주소인데 장소가 없으면(구글 화면 위치·좌표만, 카카오 주소에 ID 없음) 422 `LINK_UNRESOLVED`.
- **구글**: 이름(`/place/<이름>` 또는 `?q=`)은 `name_hint`로, 좌표는 `!3d!4d`(장소 핀)를 `@`(뷰포트)보다 먼저 써서 반경 100m 자체 DB 장소를 찾는다. **이름이 같은 곳으로 볼 만한(`NAME_MIN_SCORE` 0.8) 후보만** `matches`에 담는다(가까운 순 최대 5) — 스펙은 반경만 적었지만 같은 건물의 다른 가게가 핀 후보로 올라가지 않게 `match_place`와 같은 이름 기준을 더했다. 좌표 없는 링크(`?q=`)는 DB를 보지 않고 `name_hint`만 준다. `needs_search_query`는 항상 false.
- **카카오**: `kakao_place_id`(`kakao:<id>`)만 뽑는다. 자체 DB에 그 ID가 기록된 장소가 있으면 `matches`, 없으면 `needs_search_query=true`. 카카오 API는 부르지 않는다.
- **`matches[].place_id`**: 자체 DB 장소에 카카오 ID가 기록돼 있으면 그 값, 없으면 `own:<places.id>`. FE는 그대로 `POST /maps/{id}/pins`(`source: search`)에 되돌려 보내면 된다(이름·좌표는 자체 DB 값이라 `match_place`가 같은 장소를 찾는다). `own:` 값은 카카오 ID가 아니라서 핀 생성이 `kakao_*`로 기록하지 않는다. **스펙 `PlaceSearchResult.place_id` 설명에 `own:<id>` 형태 한 줄을 추가해 주세요**(루트).
- **SSRF 방어**(`linkfetch.py`, 단축 호스트 `maps.app.goo.gl`·`goo.gl`·`kko.to`만 가져온다):
  - http(s)만, 포트 80/443만, 사용자 정보(`user:pw@`) 거부, 호스트는 도메인 허용목록(정확히 같거나 하위 도메인 — `google.com.evil.com`·`evilgoogle.com`은 막힘).
  - 리다이렉트는 직접 따라가고(최대 4회) **매 홉마다** 허용목록·포트·스킴을 다시 검사한다. 허용 밖으로 가면 요청을 보내지 않고 멈춘다.
  - 매 홉 DNS를 풀어 **모든 주소가 공인 IP**(사설·루프백·링크로컬·CGNAT·예약·멀티캐스트·IPv4-매핑 IPv6 차단)일 때만 접속하고, 검사한 IP로 직접 접속한다(`Host`·SNI는 원래 호스트) — 검사 뒤 DNS가 바뀌는 rebinding을 막는다.
  - 타임아웃 3초, 본문은 읽지 않는다(헤더의 `Location`만 보고 닫음 — 크기 제한이 따로 필요 없다). 이미 긴 지도 주소는 가져오지 않고 바로 읽는다. 환경 프록시는 쓰지 않는다(`trust_env=False`).
  - 열지 못하면(허용 밖 이동·사설 IP·횟수 초과·타임아웃·리다이렉트 아님) 422 `LINK_UNRESOLVED`.
- **로그·응답**: 링크 주소·이름·좌표를 로그에 남기지 않는다(`places.link provider=… matches=N`, 실패 시 사유 종류만). 응답에는 링크의 좌표를 싣지 않는다(`matches`의 좌표는 자체 DB 값). 테스트가 로그에 이름·좌표·ID·도메인이 없음을 고정한다.
- **호출 상한**: `PLACES_SEARCH_PER_MIN`(기본 30)과 같은 값을 쓰되 `/places/search`와 **따로 센다**(`link_limiter`, 사용자당). 순서는 422(본문 형식) → 429 → 해석. 로그인 필요, 지도 구성원 여부는 보지 않는다.
- **테스트**: `places/tests/test_link.py`(80개, DB·네트워크 없음 — 파서·SSRF·짝 찾기·로그·라우트), `test_own_db.py`(실제 DB 조회 3개), `integration/test_places_search.py`(링크 → 핀 생성 왕복, 429, 401), 골든 패스(`test_response_contract.py`)에 4호출 추가. `KNOWN_MISSING`·`KNOWN_UNCOVERED`에서 `/places/from-link`를 지웠다. backend 전체 1914 passed.
- **실제 구글·카카오 단축 링크로는 아직 시험하지 못했다**(테스트는 `httpx.MockTransport`). 실서버 연동 점검에서 `maps.app.goo.gl/…`와 `kko.to/…` 실링크 한 개씩 확인이 필요하다 — 특히 단축 링크가 `consent.google.com` 같은 동의 화면으로 먼저 보내는 경우(이때는 `LINK_UNRESOLVED`로 떨어진다).

---

# #473 GET /places/nearest 구현 (2026-10-15)

- **동작**: `lat`·`lng`(+`category`) 기준 100m 안의 자체 DB 장소(`status='open'`)를 가까운 순 최대 5곳. `ST_DWithin`(geography) + `ST_Distance` 정렬, `idx_places_geom`(GiST)을 탄다 — 계획 확인은 `integration/test_places_nearest.py::test_query_uses_the_gist_index`(작은 테이블은 순차 스캔이 이기므로 `enable_seqscan=off`로 계획만 본다). 숙소·기타는 빈 배열, 모르는 분류는 422.
- **pinnable=true만**: 후보 10곳을 읽고, 핀 생성이 부를 `match_place`와 같은 규칙(`find_candidates_many` + `pick_match`, 자기 이름·좌표를 힌트로)으로 거절될 곳(같은 자리 동명 점포 등)을 뺀 뒤 5곳으로 자른다. 주소는 힌트에 넣지 않는다 — pins가 아직 주소를 안 넘긴다(#500 3개 항목이 켜지기 전 기준).
- **응답**: `place_id`=`own:<places.id>`, `place_source.provider`=`permit`|`tourapi`(url 없음), `address`·`category`는 자체 DB 값. 카카오 값은 어디에도 없다. `own:` ID로 핀을 만들어도 `pins/core.kakao_place_url`이 `kakao:` 접두어만 URL로 바꾸므로 카카오 ID로 기록되지 않는다.
- **가드레일 (#53)**: 누른 좌표는 저장·로깅하지 않는다. 쓰기 쿼리 없음. DB 오류는 예외 타입만 남기고 `503 PLACES_UNAVAILABLE`(SQL 파라미터에 좌표가 실린다). uvicorn 접근 로그는 요청 줄에 쿼리스트링을 찍으므로 `places/logguard.py`(`StripQueryFilter`, `router.py` 임포트 시 설치)가 `/places/nearest`의 쿼리를 `?[redacted]`로 바꾼다. **배포에서 접근 로그를 다른 프록시(Cloud Run 요청 로그 등)가 남기는 것은 이 필터 밖이다 — 운영 쪽 확인이 필요하다.**
- **호출 상한**: `check_search_rate` 그대로 — `GET /places/search`와 같은 사용자별 버킷(분당 `PLACES_SEARCH_PER_MIN`, 기본 30)을 공유한다. 지도를 연달아 누르면 검색 상한을 같이 쓴다.
- **스펙 보정**: `503 PLACES_UNAVAILABLE` 응답 추가(`docs/api-spec.yaml`, `CHANGELOG-api.md` 2026-10-15 네 번째). 그 외 계약 변경 없음.
- **테스트**: `integration/test_places_nearest.py` 17개(반경·정렬·최대 5·분류·폐업 제외·pinnable 거절 제외·422·401·429 공유 버킷·503 좌표 비노출·로그/저장 없음·접근 로그 필터·GiST 계획). `KNOWN_MISSING`·`KNOWN_UNCOVERED`에서 항목 삭제, 골든 패스(`test_response_contract.py`)에 nearest 호출 추가. `integration`·`places`·`common` 472 통과.
- **FE 참고**: 목 서버(`contracts/mocks`)의 nearest는 `kakao:` 형식 ID를 쓴다. 실서버는 `own:<uuid>`이고 불투명 값으로 그대로 보내면 된다.


---

# places.can_recommend 구현 (2026-10-15)

- **구현**: 마이그레이션 `0033_places_can_recommend`(not null default false, down_revision `0032_feedback`, 단일 head), 판정 규칙 `places/core.py`(순수 함수 `can_recommend(category, known_label_count, *, curated)`, 임계는 같은 파일 상수 `KNOWN_LABEL_THRESHOLDS = {"음식점": 5, "카페": 3}`·`ALWAYS_RECOMMENDABLE = {"관광지"}` 한 곳), 재계산 `repository.recompute_can_recommend`와 `python -m places.scripts.recompute_can_recommend [--dry-run]`(분류별 true/false·바뀐 수 보고, 멱등), `places.load`는 적재 끝에 같은 함수를 같은 트랜잭션에서 자동 재계산하고 건수를 출력한다(dry-run이면 같이 롤백). `PlaceRef.can_recommend: bool = True`(기본값이라 기존 호출자 그대로)를 `search_nearby_own`만 실제 값으로 채운다. 검색·핀 생성 매칭·nearest·링크 해석은 읽지 않는다(테스트로 고정).
- **정예 판별 기준 — 조사 결과**: `places.source`는 모두 `permit`이라 못 가르고, **`label_source`로도 못 가른다**. 인허가 커버리지 라벨이 정예와 같은 출처 표기(`license_*`, `franchise_brands` 등)를 쓰고, 정예 12,376곳 중 4,710곳은 확정 라벨이 전부 `license_*` 계열이다(`pingo_before499` 기준). 대신 **"출처(`label_source`)가 NULL인 라벨 행을 하나라도 가진 장소 = 정예"**가 정확히 맞는다 — 정예 납품본은 근거 없는 `unknown` 행을 항상 담고, 커버리지 라벨은 "근거 없으면 넣지 않는다"(permit README)라 NULL 행이 없다. 검증: 정예 파일 소속 집합(기존 정예 12,376 + 신규 음식점·카페·관광지 파일 = 15,181곳)과 pingo_demo의 NULL 라벨 보유 장소 15,181곳이 **양방향 차이 0**.
  - **취약점: 해결됨(2026-10-16, `places.curated` 컬럼 — 아래 「places.curated」 절).** 이 항목의 기준(출처 NULL 라벨 행)은 0034 마이그레이션이 과거 적재분을 한 번 되메울 때만 쓰고, 이후 정예 판별은 `--authoritative` 적재가 켜는 `places.curated`다.
- **인덱스를 더하지 않았다**: 후보 검색은 기존 GiST(`idx_places_geom`)로 반경을 먼저 거르고 `category`·`status`·`can_recommend`는 그 결과에 얹는 조건이다. `can_recommend`는 약 86%가 true인 불리언이라 부분 인덱스의 이득이 없다. 추천 후보 검색 계획이 느려지면 그때 `WHERE can_recommend AND status='open'` 부분 GiST를 검토한다.
- **⚠ 마이그레이션만으로는 값이 안 채워진다**: 기존 행은 모두 false다. 적용한 뒤 `recompute_can_recommend`를 한 번 돌려야 추천 후보가 생긴다(안 돌리면 후보 풀이 비어 「추천 가능 아님 제거」 단계가 전부를 뺀다). 배포 절차에 넣어야 한다.
- **재계산 결과(pingo_demo의 복사본 `pingo_cr507`, 임계 음식점 5·카페 3, 멱등 확인: 두 번째 실행 바뀐 장소 0)**:

| 분류 | true | false |
|---|---|---|
| 음식점 | 66,926 | 13,339 |
| 카페 | 23,855 | 1,313 |
| 관광지 | 723 | 0 |
| 합계 | 91,504 | 14,652 |

  정예 15,181곳은 전부 true(false 0). 임계 이상인데 false인 장소 0. false인 음식점의 확정 라벨 수는 0개 13곳·1개 9,636·2개 3,618·3개 72(임계 5 미만 전부). 루트가 준 참고 분포와 맞는다.
- **⚠ pingo_demo 마이그레이션 적용 — 아직 안 했고, 알릴 것이 있다**: pingo_demo의 `alembic_version`이 **`0020_evidence_wants`**다. 0033을 적용하면 0021~0032까지 열두 단계가 함께 올라간다(테이블 18개 → 28개, agent·notifications·feedback 등 새 테이블 추가). 복사본에서는 오류 없이 head(`0033_places_can_recommend`)까지 올라갔다. 기존 데이터를 바꾸는 단계가 있는지는 단계별로 확인하지 않았다. pingo_demo를 바꾸는 작업이라 사용자 확인을 받은 뒤에 한다. 백업 `C:\Users\user\Desktop\pingo_demo_before507.dump`(#507 적재 직전 상태)는 그대로 있으나, **#507 장소 적재 이후의 pingo_demo는 이 백업에 없다** — 적용 직전에 새로 백업을 뜬다.
- **커버리지 새 라벨 750개(restaurant-labels 단계)**: 하지 않았다(메모리). 해당 라벨이 들어가면 일부 커버리지 장소의 확정 라벨 수가 늘어 can_recommend 건수가 소폭 달라질 수 있다 — 적재 끝의 자동 재계산이 반영한다.
- **테스트**: `places/tests/test_can_recommend.py`(규칙 파라미터화·임계 상수·재계산 임계/정예 보존/멱등/라벨 변화 양방향/dry-run/폐업 포함/스크립트/적재 자동 재계산·PlaceRef 필드와 기본값·검색·nearest 무관) + `test_can_recommend_migration.py`(단일 head·up/down·기존 행 false·모델 일치). `places`·`integration`·`common` 609 통과.


---

# places.curated — 정예 표시 컬럼 (2026-10-16)

- **구현**: 마이그레이션 `0034_places_curated`(`curated boolean not null default false`, down_revision `0033_places_can_recommend`, 단일 head). **되메우기는 이 마이그레이션 안에서 휴리스틱("출처(`label_source`)가 NULL인 라벨 행을 가진 장소 = 정예")으로 한 번만** 채운다. 그 뒤로는 휴리스틱을 쓰지 않는다. down은 컬럼 삭제.
- **로더**: `--authoritative` 적재(`existing_mode="overwrite"`)가 같은 (source, source_id)의 `curated`를 true로 켠다. 이미 있던 커버리지 장소를 정예가 덮을 때도, 신규 정예 행도 true다. 커버리지(`permit`, `keep`)와 기본(`refresh`) 적재, 재계산은 `curated`를 끄지도 켜지도 않는다(한 번 true면 유지). 폐업 처리도 `curated`를 건드리지 않는다.
- **`recompute_can_recommend`**: 정예 판별을 라벨 NULL 휴리스틱에서 `places.curated`로 교체했다(라벨 집계 쿼리는 확정 라벨 수만 센다).
- **결과가 #561 보고와 같다(복사본 `pingo_cur507` = 현재 pingo_demo에서 새로 뜸, 0021~0034 적용 뒤 재계산)**: 음식점 66,926 / 13,339, 카페 23,855 / 1,313, 관광지 723 / 0(true / false), 합계 91,504 / 14,652. `curated=true` 15,181곳이 전부 `can_recommend=true`(예외 0). 두 번째 실행에서 바뀐 장소 0(멱등). 불일치 없음.
- **#561 조사 결과의 취약점 항목: 해결됨.** 정예 판별이 더는 "납품본에 근거 없는 unknown 행이 있다"는 데이터 관례에 기대지 않는다. 납품 형식이 바뀌어도 `--authoritative`로 적재하면 정예로 표시된다. 휴리스틱은 0034 되메우기에만 남는다(과거 적재분 한 번).
- **테스트**: `test_curated_flag.py`(적재가 켬·신규 정예 행·커버리지/refresh/폐업/재계산이 끄지 않음·기본 false), `test_curated_migration.py`(단일 head·되메우기 한 번(NULL 라벨만 true)·up/down·모델 일치), `test_can_recommend.py`를 `curated` 컬럼 기준으로 갱신(NULL 라벨이 더는 정예 신호가 아님·재계산이 정예를 끄지 않음). `places`·`common`·`integration` 중 통합 계약 테스트 몇 개가 실패하는데 **develop 원본에서도 같은 계열이 실패한다**(알림·피드백·협업 계약 테스트, 실행마다 실패 조합이 달라짐 — 이 PR과 무관한 기존 불안정, 별도 확인 필요).

## pingo_demo 마이그레이션 단계별 조사 (0020 → 0034, 14단계)

pingo_demo는 `alembic_version=0020_evidence_wants`다. 단계별로 `upgrade()`를 읽고, **현재 pingo_demo의 복사본에 실제로 올려서** 기존 테이블 행 수를 비교했다(오류 없이 head `0034_places_curated`까지 올라감).

| 단계 | 내용 | 기존 행 영향 |
|---|---|---|
| 0021_maps_delete_leave | `maps.deleted_at` 추가, `memberships` 방장 1명 유일 인덱스 | 값 변경 없음. **방장이 2명 이상인 지도가 있으면 RuntimeError로 중단**(지금 데이터는 해당 없음, 복사본 통과) |
| **0022_reaction_two_state** | **`DELETE FROM reactions WHERE type='neutral'`** 후 enum을 like·against 둘로 교체 | **기존 행을 지운다.** pingo_demo reactions 20행 중 neutral 6행(like 9·against 5는 남음)이 삭제된다. downgrade로도 지운 행은 돌아오지 않는다. 지운 사람의 사유는 evidence_lines에 남는다고 마이그레이션 주석에 적혀 있다 |
| 0023_pins_live | `pins`에 source(기본 'db')·kakao_place_id·search_query·memo 추가, `place_id`·`geom` NOT NULL 해제, 체크 제약·유일 인덱스 | 값 삭제 없음. 기존 28핀은 전부 `source='db'`로 채워진다. 체크 제약이 기존 행에 통과함을 복사본에서 확인 |
| 0024_evidence_lines_seq | `evidence_lines`에 identity `seq` 추가 | 테이블 재작성, 기존 30행에 1~30이 매겨진다. 값 삭제 없음 |
| 0028_recommend_runs_history_idx | 인덱스 추가 | 없음 |
| 0025_invite_revoke | `invites`에 revoked_at·created_at(기본 now()) 추가, 인덱스 | **기존 9개 초대의 created_at이 전부 적용 시각 한 값이 된다**(원래 생성 시각을 알 수 없음). 삭제는 없음 |
| 0029_agent_tables | agent 테이블 7개 CREATE | 없음(새 테이블) |
| 0030_agent_cursor_drop_gap_seq | `agent_cursors.gap_seq` 컬럼 삭제 | 0029에서 방금 만든 빈 테이블의 컬럼이라 영향 없음 |
| 0031_notifications | notifications·notification_prefs CREATE | 없음 |
| 0032_feedback | feedback CREATE | 없음 |
| 0033_places_can_recommend | `places.can_recommend` 추가(기본 false) | 값 변경 없음(재계산 전까지 전부 false) |
| 0034_places_curated | `places.curated` 추가 + 휴리스틱 되메우기 UPDATE | places의 새 컬럼만 채운다. 기존 컬럼 불변 |

- **요약**: CREATE TABLE·ADD COLUMN·인덱스가 대부분이고, **기존 행을 건드리는 것은 두 곳**이다. ① 0022가 reactions의 neutral 6행(20행 중)을 **삭제**한다. ② 0025가 invites 9행의 created_at을 적용 시각으로 채운다. 그 외에 0021은 방장 중복이 있으면 적용이 중단된다(지금은 해당 없음).
- **복사본 실측**: 적용 전후 행 수가 같은 테이블은 candidates 12·event_log 70·evidence_lines 30·exclusions 0·invites 9·maps 6·memberships 15·pins 28·place_facts 1,027,876·places 106,156·recommend_runs 11·regions 11·routes 2·shortlist_items 6·users 7. **reactions만 20 → 14**로 줄었다.
- **참고**: 조사 중 pingo_demo의 `place_facts`가 1,027,876행(커버리지 라벨 새 키 750개 포함, 장소 106,156)이다 — #507 보고에 "미완료"로 적은 상태(1,027,126)와 다르다. 누군가 커버리지 라벨 단계를 마친 것으로 보이며 이 세션은 하지 않았다. 지금 복사본·재계산 숫자는 그 상태 기준이다.
- **pingo_demo에는 적용하지 않았다.** 적용 여부는 루트가 백업(pg_dump) 후 정한다. 적용하면 reactions 6행이 사라지므로, 그 행이 시연 데이터에 필요하면 먼저 따로 보관해야 한다. 백업은 적용 직전에 새로 떠야 한다(`pingo_demo_before507.dump`는 #507 적재 이전 상태).


# 적재 로더 3건 — 지역 해제·레포츠(28)·`--close-missing` (데이터 담당 요청, 2026-10-20)

요청 출처는 데이터 담당이다(이슈 번호 없음). 마이그레이션 없음, `can_recommend` 판정 코드는 그대로다. 한 PR(브랜치 `feat/places-loader-region-leisure-close`)에 커밋 3개.

## 1. `--all-regions` — permit·tourapi·cafes·restaurants
- 켜면 서울 판정 세 곳(주소 "서울", TourAPI `areacode`, 서울 좌표 상자)을 모두 끈다. 기본은 서울만. 설명에서 "테스트용"을 지웠다.
- 좌표 없음·(0,0)·위경도 범위 밖(한국 상자 밖)은 지역을 풀어도 계속 건너뛴다.
- 보고: 적재 대상이 두 지역 이상이면 `[지역별 적재 대상] 서울 N, 부산 M …` 한 줄이 붙는다(서울만이면 안 붙는다). 시도명 앞 두 글자 기준이되 충청·전라·경상은 북·남이 갈리도록 `충북·경남`처럼 쓴다(앞 두 글자만 쓰면 둘이 합쳐진다).
- 주의: 지금 DB의 `places`는 서울 가정으로 검색한다. 타 지역을 적재하면 서울 밖 좌표로도 후보가 잡히므로 서비스 쪽 영향은 적재 전에 루트가 판단한다.

## 2. 관광지 레포츠(contenttypeid 28)
- `TOURAPI_PLACE_TYPES`에 28 추가, 분류는 관광지. 건너뛰기 사유 문구는 `관광지·문화시설·레포츠·쇼핑(contenttypeid=12·14·28·38) 아님`. 로더 docstring·`docs/data-model.md` places 절의 한 줄 설명만 맞췄다(그 밖의 스펙은 안 바꿨다).

## 3. `permit --close-missing` (기본 꺼짐)
- 파일에 없는 장소를 `status='closed'`로 바꾼다(삭제·라벨 삭제 없음). 대상은 `source='permit'`·`curated=false`·`status='open'`뿐이다 — 정예와 tourapi는 닫지 않는다(UPDATE에도 같은 조건을 다시 건다).
- 안전장치: ① `--file`을 여러 번(또는 디렉터리 → 안의 `*.csv`, 글롭) 받아 모두 읽은 뒤에만 닫고, 파일 하나면 거부(exit 2). ② 위 대상 한정. ③ `--dry-run`이 `DB: 파일에 없어 닫음 N행`을 보인다(롤백). ④ 파일에 다시 나온 기존 열린 비정예 인허가 장소가 그 장소의 30% 미만이면 거부(`--force`로만 우회) — 거부면 신규 적재도 하지 않는다. ⑤ 라벨은 그대로.
- '파일에 있다'의 기준은 관리번호가 있는 모든 행이다. 좌표 없음·업태 미대응 등으로 건너뛰는 행도 '있다'로 센다(그런 장소를 닫지 않는다).
- **되살리기 수정**: 확인해 보니 인허가 로더(`keep` 모드)는 이미 있는 장소를 통째로 건너뛰어, 닫힌 장소가 파일에 영업으로 다시 나와도 열리지 않았다(`refresh` 경로만 열었다). `keep`에서도 닫힌 장소는 `status`만 다시 열도록 했다(이름·분류·좌표는 그대로). 보고에 `되살림 N행`이 붙는다. 이전 동작에서 닫힌 채 남던 장소가 다음 인허가 적재 때 열린다는 점이 달라졌다.
- 정예 우선 결정의 "갱신본에서 빠진 657행은 그대로 둔다"는 그대로다 — 옵션을 안 주면 아무것도 닫히지 않는다.

## 테스트
`places/tests/test_ingest.py`(지역 해제·28·`region_of`·닫기 계획), `places/tests/test_load_regions_close.py`(옵션 전달·닫기 대상·안전장치·dry-run·되살리기). places 전체 406 통과. `test_link.py` 3건은 `authz.guard`↔`auth.deps` 순환 import로 이 변경과 무관하게 실패한다(`python -c "import authz.guard"` 단독 재현).


# #682 관광지 검색(CT1·정확도 순) · #674 search_own_by_name (2026-10-24)

## #682 — `backend/places/sources/kakao.py`
- 카카오 문화시설(CT1: 박물관·미술관·공연장)을 `"관광지"`로 매핑한다(`_GROUP_CODES`: 관광지 = AT4 + CT1). 키워드 검색 응답의 분류가 "기타"가 되던 것이 사라지고, 핀을 찍을 수 있는지는 지금처럼 자체 DB 짝 여부(`pinnable_flags`·`match_place`)로 정한다.
- 카테고리 검색(`search_nearby`)은 관광지에서 AT4·CT1을 각각 불러 같은 id는 한 번만 두고 가까운 순으로 합친다 — **관광지는 카카오 호출이 코드당 최대 페이지 수만큼, 즉 두 배**가 된다(`max_pages` 기본 2 → 최대 4회). CT1 호출이 실패하면 AT4 결과는 유지하고, AT4(첫 코드) 첫 페이지 실패는 지금처럼 소스 실패로 올린다. 반경 제한은 그대로다.
- 키워드 검색(`search_by_name`)은 `sort=accuracy`로 바꿨다. 좌표가 있으면 `x`·`y`를 같이 보내 가까운 곳을 약하게 우대받고, **반경 제한은 지금처럼 없다**(#351 범위 결정과 어긋나지 않는 최소 변경). 좌표가 없을 때도 같은 정확도 순이다(전엔 sort 파라미터가 없었다).
- 확인 못 한 것: 실제 카카오로 "경복궁"을 불러 본체가 상위에 오는지는 **목 응답으로만** 검증했다(요청에 `sort=accuracy`가 가고 응답 순서를 그대로 유지하는 것까지). 라이브 확인은 키가 있는 환경에서 해야 한다.
- FE: `frontend/src/features/map/livePlaces.ts`의 `GROUP_CODE`에 CT1 → "관광지"가 필요하다(FE 몫, 건드리지 않았다).

## #674 — `places.api.search_own_by_name(db, *, query, category=None, limit=20) -> list[dict]`
- 이슈의 시그니처·규칙 그대로: 자체 DB `places.name` 부분 일치(대소문자 무시), status 무관(closed 포함), `[{id, name, address, category, status}]`, 읽기 전용·커밋 없음.
- 정한 것: 이름순은 **코드포인트 순**(`COLLATE "C"`)이다 — DB 로캘에 따라 공백이 무시돼 순서가 달라지는 것을 막았다(한글은 가나다순과 같다). `%`·`_`는 글자 그대로 찾고, 빈 질의·`limit<=0`은 빈 목록, `category`가 자체 DB 분류가 아니면 빈 목록이 된다.
- ads의 `find_place`와 등록 스크립트 status 확인 교체는 ads 몫이다.

## 테스트
`test_sources.py`(CT1 매핑·합치기·부분 실패), `test_name_search.py`(정확도 순·반경 없음·본체 우선), `test_search_own_by_name.py`.


# #690 영업시간·휴무일 — place_hours·get_hours·is_open_on·place-hours 로더 (2026-10-24)

스펙(PR #693: `data-model.md` place_hours, `constraints.md` 영업 중 판정, `architecture.md` get_hours)대로 구현했다. 스펙·docs는 바꾸지 않았다.

## 만든 것
- **마이그레이션 `0038_place_hours`**(down `0037_agent_course_runs`, 단일 head): `place_hours(place_id PK→places on delete cascade, hours jsonb, closed_days text[], closed_note, hours_note, updated_at)`. 모델 `places.models.PlaceHours`와 일치하는지 테스트가 본다. **다른 PR이 먼저 0038을 쓰면 번호를 올려야 한다**(병합 순서에 따라).
- **`places.api.get_hours(place_ids, *, db=None) -> dict[str, PlaceHours]`**: 한 번의 IN 조회, 행 없는 장소·잘못된 id는 키에서 뺀다, 읽기 전용. `PlaceHours(hours, closed_days, closed_note, hours_note)`는 `places/schemas.py`(frozen dataclass).
- **`places.core.is_open_on(hours, closed_days, weekday, minutes) -> "open"|"closed"|"unknown"`**: 스펙 그대로. **`weekday`는 0=월 … 6=일(`date.weekday()`와 같다), `minutes`는 0~1439**이고 범위 밖이면 ValueError — 호출하는 쪽(recommend)이 맞춰야 하는 약속이다. 한 가지 스펙에 없던 해석: `hours`는 있는데 그 요일 키만 빠진 경우(로더는 요일 7개가 아니면 hours를 버리므로 DB에는 안 생긴다)는 `closed_days`로 넘어간다. `core.parse_minutes("HH:MM"|"26:00")`도 공개.
- **로더 `python -m places.load place-hours --file <라벨 JSON | tourist_seoul_closed_days.json> [--all-regions] [--dry-run]`**: `rest_`·`cafe_` → permit, `tour_` → tourapi, 서울 관광지 파일은 `source_id`(=contentid) → tourapi. 멱등(같은 장소는 파일 값으로 갱신), 파일에 없는 장소·칸이 없는 항목의 기존 행은 지우지 않는다, 장소를 못 찾으면 건수만 보고한다. 항목에 `addr1`이 있고 서울이 아니면 `--all-regions` 없이는 건너뛴다(주소 없는 항목은 판단하지 않는다 — 장소가 DB에 있는지는 어차피 못 찾음 건수로 나온다). 기존 restaurants·cafes·tourapi의 라벨 적재는 그대로(`info`를 읽지 않는다, 테스트로 고정).
- **형식 검증**: hours는 요일 7개 모두 + `[여는, 닫는]`이 `HH:MM`(시작 < 24:00, 시작 < 끝 ≤ 48:00)이어야 하고, 아니면 hours 칸만 버리고 경고(다른 칸이 있으면 행은 만든다). closed_days는 월~일 이름만. 칸이 하나도 안 남으면 행을 만들지 않는다.

## 공유본(2026-10-21) 파싱 확인 (DB에는 쓰지 않음)
정예 라벨 JSON 18개를 `parse_hours_entries`로 읽어 본 결과 형식 경고 0건. 행이 생기는 수: 서울 음식점 1,342/1,355, 카페 1,516/1,676, 관광지(closed_days 파일) 723/723, 대전·춘천·광주·대구·부산은 README 채움률과 일치. 나머지는 칸이 없어 행이 없다(= 모름).

## 루트 확인
- 적재 순서: 장소를 먼저 적재한 뒤 `place-hours`를 돌린다(장소가 없으면 못 찾음으로 센다). 지역 라벨 파일에는 `addr1`이 있는 관광지만 주소 판정이 걸리므로 지역은 `--all-regions`를 주면 된다.
- 마지막 `can_recommend` 재계산은 다른 적재 명령처럼 `place-hours`도 돌린다(값은 안 바뀐다).

## 테스트
`places/tests/test_place_hours.py`(경계·파싱·적재·get_hours), `test_place_hours_migration.py`(up/down·단일 head·모델 일치).
