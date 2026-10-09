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
| 라벨 파일 | 형식은 architecture.md/data-model.md(#196) 그대로. 허용 `fact_key`는 **`docs/constraints.md` 표의 첫 열에서 읽는다**(코드에 목록을 복제하지 않는다. `is_open`·`within_radius`는 제외) + `contains_*` 접두 재료 태그. 모르는 키·잘못된 값은 건너뛰고 건수 보고, 같은 키가 여럿이면 마지막 줄(경고), 멱등 upsert, 파일에 없는 키는 건드리지 않음. 값은 참/거짓만 받는다 — 원본 숫자는 저장되지 않는다. `source_layer`는 3. `unknown`이면 `value`는 SQL NULL(JSON null 아님) |
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
