# 추천 탭 광고

상태: 설계 (2026-10-19), 이슈 #642. v2 범위(2026-10-19 결정). 계약은 `docs/api-spec.yaml`의 ads 태그가 정본이고, 이 문서와 다르면 정본을 따르고 루트에 보고한다.

이 문서는 Claude Code가 구현 전에 읽는 명세다. "결정"은 확정된 내용이고, "(제안)"은 기본값으로 정했지만 팀 확인을 기다리는 내용이다. 2026-10-19 판의 "확인 필요"는 코드를 확인해 채웠다(각 항목에 근거).

## 1. 목적과 범위

AI 추천 탭 하단에 광고 장소를 최대 2개 상시 노출한다. 광고 장소는 카카오맵에서 정보를 보거나 「지도에 올리기」로 지도에 올릴 수 있다.

범위 밖 (이번에 만들지 않는다)

- 광고 사진, 광고 문구
- 관리자 화면 (관리 스크립트로 대신한다, 8절)
- 화면에 실제로 보인 시점 기준의 노출 집계 (9절 "다음 단계"에서 다룬다)
- 사용자 단위 기록, 타게팅, 노출 빈도 조절, 과금
- 지도에 올린 핀의 광고 표시
- 광고 장소의 앱 안 상세 화면 (4절, 카카오맵 링크로 대신한다)

## 2. 넘지 말 것

1. 광고는 자체 DB(places)에 이미 있는 장소만 받는다. 광고 때문에 places 행을 새로 만들거나 places.source 값을 추가하지 않는다. (결정: 좌표 변환 결과의 저장 약관 문제로 광고주 데이터 적재는 보류)
2. 광고는 AI 추천의 후보 풀과 순위에 들어가지 않는다. recommend 모듈은 ads를 import하지 않고, 광고 여부를 입력으로 받지 않는다. 광고가 places.can_recommend 값을 바꾸지 않는다.
3. 광고 선택은 코드로 한다. 모델을 부르지 않는다.
4. 광고는 반응과 실격 필터를 거치지 않는다. 그룹이 반대했거나 실격 조건에 걸리는 장소도 광고로 노출된다. 대신 광고 칸에는 이유, 조건별 충족 체크, 구성원 충족 집계를 보여주지 않는다.
5. 광고 영역은 추천 결과 영역과 분리하고 "광고" 표시와 시각적 구분을 분명하게 둔다. 추천 결과 0개 문구는 광고가 있든 없든 그대로 보여준다(가드레일 2).
6. 광고에서 지도에 올린 핀은 일반 핀이다(pins.source = db, pins.origin = direct). pins에 광고 흔적을 남기지 않고, 올라간 뒤에는 다른 핀과 똑같이 반응, 확정, 에이전트 관찰 대상이 된다.
7. 노출과 클릭은 광고별 날짜별 집계만 남긴다. user_id, map_id를 집계 테이블에 넣지 않는다.
8. 카카오 응답 저장 금지(#53)는 광고에도 그대로 적용된다. 광고 칸의 정보는 places 행에서만 읽는다. 카카오맵 링크도 places에 이미 기록된 `kakao_place_url`만 쓴다.

## 3. 용어

- 광고(ad): 기간을 정해 추천 탭 하단에 노출하는 places 행 하나
- 광고 영역: AI 추천 탭 하단의 광고 칸 묶음
- 광고 칸: 광고 하나를 보여주는 화면 요소

"장소 카드"는 프로젝트 용어 규칙상 쓰지 않는다.

## 4. 화면 (frontend)

위치와 노출

- AI 추천 탭 하단에 고정한다. 추천 결과 영역과 구분된 별도 영역이다.
- 추천 전, 로딩 중, 결과 있음, 결과 0개, 실패 상태 모두에서 노출한다.
- 광고가 0개면 광고 영역을 그리지 않는다. (제안)

광고 칸 내용

- 장소 이름, 카테고리, 주소 (places 행 기준)
- "광고" 배지
- 버튼 두 개: 「카카오맵에서 보기」, 「지도에 올리기」
- 「카카오맵에서 보기」는 응답의 `place_url`이 있을 때만 보여 주고 새 창으로 연다(앱 안 WebView 금지, 카카오 약관). 추천 카드도 같은 방식이다(#632에서 앱 안 후보 상세를 지우고 카카오맵 링크로 바꿨다). 그래서 광고에도 앱 안 상세 화면을 만들지 않는다.
- 그 장소가 이미 이 지도에 핀으로 있으면(on_map = true) 「지도에 올리기」 대신 비활성 버튼 "이미 지도에 있어요"를 보여준다. 광고 칸 자체는 그대로 노출한다.

조회 시점

- 탭을 열 때 광고 조회 API(7.1)를 한 번 부르고, 탭이 열려 있는 동안은 결과를 고정한다. 탭 안에서 다시 부르지 않는다.
- 조회 기준점은 탭을 연 순간의 지도 화면 중심 좌표다.
- 카테고리: 추천 탭은 추천 전에는 준비된 카테고리 중 하나를 고르고(Readiness, 기본은 첫 준비 카테고리), 추천 뒤에는 그 run의 카테고리를 보여 준다. 화면이 보고 있는 카테고리를 보내고, 사용자가 카테고리를 바꾸면 그때만 다시 조회한다. 준비된 카테고리가 하나도 없어 고른 카테고리가 없으면 `category` 없이 조회한다(서버가 추천 대상 카테고리 전체에서 고른다).
- 미리 불러오기(prefetch)를 하지 않는다. 조회 1회가 곧 노출 1회로 집계되기 때문이다(9절).

추천 결과와 겹칠 때

- 탭을 열 때 이미 추천 결과가 있으면 서버가 그 결과의 장소를 광고에서 뺀다(5절).
- 탭이 열린 뒤 새 추천 결과가 나와서 광고 장소와 겹치면, FE는 그 광고 칸을 숨긴다. 다른 광고로 채우지 않는다.

지도에 올리기

- 기존 핀 생성 API(`POST /maps/{mapId}/pins`, `source: search`)를 그대로 쓴다. 광고 응답의 `place.place_id`, `name`, `lat`, `lng`, `category`를 매칭 힌트로 보낸다. 자체 DB place_id가 매칭 힌트로 통하는 경로는 이미 있다(`GET /places/nearest`, #473). 그래서 pins 모듈에 새 경로가 필요 없다.
- 광고 id를 핀 생성 요청에 싣지 않는다(2절 6번).

클릭 기록

- 광고 칸에서 「카카오맵에서 보기」나 「지도에 올리기」를 누르면 클릭 기록 API(7.2)를 보낸다.
- 탭이 한 번 열린 동안 같은 광고는 한 번만 보낸다. (제안)
- 클릭 기록 실패는 사용자에게 알리지 않는다.

광고 칸 스타일은 frontend/DESIGN.md에 절을 추가해 정한다(FE 이슈).

## 5. 선택 규칙 (backend, 코드)

입력: map_id, category(없을 수 있음), center(lat, lng), 요청자 user_id

1. 후보 광고를 모은다.
   - ads.active = true
   - starts_at <= 지금 < ends_at
   - 연결된 places 행의 category = 요청 category. category가 없으면 추천 대상 카테고리(`common.categories.recommendable()`) 전체
   - 연결된 places 행의 status = open
   - ST_DWithin(places.geom, center, AD_RADIUS_M)
2. 요청자의 이 지도 최신 추천 결과에 있는 장소를 후보에서 뺀다. category가 있으면 그 카테고리의 최신 run, 없으면 카테고리마다 최신 run을 본다. recommend.api에 이 함수가 없어 새로 연다: `recommend.api.latest_run_place_ids(db, *, map_id, requested_by, category=None) -> set[str]` (recommend 이슈). 다른 구성원의 run은 보지 않는다.
3. 남은 후보에서 균등 랜덤으로 최대 AD_SLOTS개를 고른다. 후보가 AD_SLOTS개 이하면 전부 보여주고, 반경 밖에서 채우지 않는다.
4. 고른 광고마다 on_map을 계산한다. 이 지도에 삭제되지 않은 핀 중 아래 하나라도 있으면 true다.
   - 같은 place_id의 db 핀(`pins.api.list_place_ids_on_map`, 이미 있음)
   - places 행에 kakao_place_id가 있고, 같은 kakao_place_id의 실시간 핀(#382). 실시간 핀에는 place_id가 없어서 이걸 보지 않으면 같은 장소를 한 번 더 올릴 수 있다. pins.api에 새로 연다: `pins.api.list_live_kakao_ids_on_map(db, *, map_id) -> set[str]` (pins 이슈)

상수 (ads/constants.py)

| 이름 | 값 | 설명 |
|---|---|---|
| AD_SLOTS | 2 | 한 번에 보여주는 광고 수 상한 |
| AD_RADIUS_M | 5000 | 화면 중심에서의 반경. 이웃한 구까지 덮는 크기(대중교통 20~30분)로 잡은 시작값. 3000m(구 하나)에서 넓혔다(2026-10-19 결정, 실측 아님) |
| AD_STATS_TZ | Asia/Seoul | 집계 날짜를 자르는 기준 시간대 |

반경 검색은 places의 기존 GiST 인덱스(idx_places_geom)를 그대로 쓴다. 광고 테이블과 places는 다른 모듈이라 ads가 places 테이블을 직접 조인하지 않는다. places.api에 광고용 읽기 함수를 연다(아래 6절 "모듈").

## 6. 데이터 모델

### ads

| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | uuid PK | |
| place_id | text not null | 광고할 장소(places.id). 모듈 경계라 FK는 걸지 않고 등록 스크립트가 존재를 검증한다 |
| starts_at | timestamptz not null | 노출 시작 |
| ends_at | timestamptz not null | 노출 끝 (이 시각은 포함하지 않음) |
| active | boolean not null default true | 기간과 별개로 즉시 내리는 스위치 |
| memo | text null | 광고주, 계약 메모 (내부용, 응답에 내보내지 않음) |
| created_at, updated_at | timestamptz not null | |

- CHECK(starts_at < ends_at)
- 카테고리는 저장하지 않고 places.category에서 읽는다. 같은 값을 두 곳에 두면 어긋날 수 있기 때문이다.
- 같은 장소에 active 광고는 하나만 둔다: 부분 유니크 (place_id) where active. (제안)

place_id에 FK를 걸지 않는 이유: 다른 모듈 테이블을 가리키는 FK를 두지 않는 것이 이 프로젝트의 관례다(agent, pins.source_run_id와 같음). 장소가 정리되면 광고는 선택 규칙 1번(places 행이 없으면 후보에서 빠짐)으로 자연히 안 나온다.

### ad_daily_stats

| 컬럼 | 타입 | 설명 |
|---|---|---|
| ad_id | uuid not null, FK ads.id | 같은 모듈이라 FK를 건다 |
| stat_date | date not null | AD_STATS_TZ 기준 날짜 |
| served_count | integer not null default 0 | 광고 조회 응답에 실린 횟수 (9절) |
| click_count | integer not null default 0 | 클릭 기록 횟수 |

- PK(ad_id, stat_date)
- 증가는 INSERT ... ON CONFLICT (ad_id, stat_date) DO UPDATE SET 칸 = 칸 + 1 로 한다.

### 모듈

새 모듈 backend/ads/가 ads, ad_daily_stats를 소유한다(결정, 루트). 다른 모듈 데이터는 api.py로만 읽는다(#113).

| 읽는 것 | 함수 | 상태 |
|---|---|---|
| 광고 장소 정보와 반경, 상태, 카테고리 필터 | `places.api.get_ad_places(db, *, place_ids, center, radius_m, categories) -> list[dict]` (id, name, category, address, lat, lng, kakao_place_id, kakao_place_url, open인 것만, 반경 안만) | 새로 연다 (places 이슈) |
| 요청자의 최신 추천 결과 장소 | `recommend.api.latest_run_place_ids` | 새로 연다 (recommend 이슈) |
| 이 지도의 db 핀 장소 | `pins.api.list_place_ids_on_map` | 이미 있다 |
| 이 지도의 실시간 핀 카카오 장소 ID | `pins.api.list_live_kakao_ids_on_map` | 새로 연다 (pins 이슈) |

import 방향은 ads → places, recommend, pins 한쪽뿐이다. recommend는 ads를 import하지 않는다(2절 2번, 테스트로 고정).

## 7. API

### 7.1 광고 조회

GET /maps/{mapId}/ads?category={category}&lat={lat}&lng={lng}

- 권한: 그 지도의 구성원(`require_map_member`, 별도 권한 액션 없음. 조회 전용 GET의 관례). 비구성원 404
- category: 선택. 있으면 추천 대상 카테고리(음식점, 카페, 관광지) 중 하나
- lat, lng: 필수, 범위 -90~90, -180~180
- 응답 200

```json
{
  "ads": [
    {
      "ad_id": "uuid",
      "place": {
        "place_id": "string",
        "name": "string",
        "category": "카페",
        "address": "string 또는 null",
        "lat": 37.5,
        "lng": 127.0,
        "place_url": "string 또는 null"
      },
      "on_map": false
    }
  ]
}
```

- ads는 0개에서 AD_SLOTS개다.
- place.lat, lng는 「지도에 올리기」의 매칭 힌트로 쓴다(자체 DB 좌표라 저장, 노출 가능, #190). place_url은 places에 기록된 카카오 장소 링크다.
- 부수 효과: 응답에 실린 광고마다 served_count를 1 올린다. 조회와 같은 트랜잭션에서 한다.
- 응답 헤더 Cache-Control: no-store
- 오류: category가 추천 대상이 아니거나 lat, lng가 범위를 벗어나면 422 `VALIDATION_ERROR`(기존 코드, 새 코드 없음)
- GET이 집계를 쓰는 구조라 미리 불러오기나 재시도가 노출을 부풀린다. 이 오차는 A 방식(9절)의 알려진 한계로 받아들인다.

### 7.2 클릭 기록

POST /ads/{adId}/clicks

- 본문: { "map_id": "string" } (권한 확인용, 저장하지 않음)
- 권한: 그 지도의 구성원(별도 권한 액션 없음). 비구성원 404
- 응답 204. 광고가 없으면 404 `NOT_FOUND`.
- click_count를 1 올린다. 기간이 끝났거나 active가 false여도 광고 행이 있으면 센다. (제안: 탭을 연 뒤 기간이 끝나는 경우가 있기 때문)

SSE 이벤트는 추가하지 않는다.

## 8. 광고 등록 (관리 스크립트)

관리자 화면 없이 스크립트로 시작한다.

- python -m ads.scripts.find_place "<이름 일부>" --category 카페: places에서 이름으로 후보를 찾아 place_id, 이름, 주소, status를 출력한다. 등록할 place_id를 사람이 고른다.
- python -m ads.scripts.register --csv <경로>: CSV 칸은 place_id, starts_at, ends_at, memo. 행마다 places 행이 있는지, status가 open인지, 기간이 맞는지 검증하고, 하나라도 틀리면 아무것도 넣지 않는다.
- python -m ads.scripts.deactivate <ad_id>: active를 false로 바꾼다.
- 집계 확인은 SQL로 한다. 자주 쓰는 쿼리 예시를 스크립트 README에 둔다.

스크립트도 places를 places.api로만 읽는다.

광고주가 늘거나 비개발자 팀원이 직접 등록해야 할 때 관리자 화면을 다시 검토한다.

## 9. 노출 집계 방식

결정: A 방식(서버 응답 기준)으로 시작한다.

- 노출 1회 = 광고 조회 API 응답에 그 광고가 실린 1회
- 사용자가 스크롤하지 않아 보지 못한 광고도 센다. 그래서 실제보다 많이 세고, 클릭률(click_count / served_count)은 실제보다 낮게 나온다.
- 칸 이름을 served_count로 둔 이유는 이 값이 "화면 노출"이 아니라는 걸 이름에서 드러내기 위해서다.

다음 단계: 실제 광고주에게 노출 기준으로 비용을 받게 되면, FE가 화면에 보인 시점을 감지해 보내는 B 방식을 검토하고 viewed_count 칸을 옆에 추가한다. 기존 served_count는 그대로 둔다.

## 10. 함께 갱신한 문서 (#642)

- docs/data-model.md: ads 절
- docs/api-spec.yaml: ads 태그, 7.1과 7.2
- docs/CHANGELOG-api.md: 구조 변경 기록
- docs/permissions.md: 광고 조회와 클릭 기록은 구성원이면 됨(새 액션 없음)
- docs/architecture.md: ads 모듈과 import 관계
- 루트 CLAUDE.md: 문서 지도
- 최종기획안.md: v2 스코프, 미결 항목 해결
- docs/errors.md: 새 코드 없음
- frontend/DESIGN.md: FE 이슈에서 광고 영역, 광고 칸, 광고 배지 절을 더한다

## 11. 테스트 체크리스트

선택 규칙 (순수 함수)

1. 기간 밖, active false, status closed, 다른 카테고리, 반경 밖 광고는 후보에서 빠진다.
2. 요청자의 최신 추천 결과에 있는 장소는 빠진다. 다른 구성원의 추천 결과는 영향을 주지 않는다.
3. 후보가 0, 1, 2, 3개 이상일 때 각각 0, 1, 2, 2개를 돌려준다. 반경 밖으로 채우지 않는다.
4. 그룹이 반대한 장소, 실격 조건에 걸리는 장소도 후보에 남는다.
5. 랜덤은 시드를 주입할 수 있게 해서 테스트에서 결과를 고정한다.
6. category가 없으면 추천 대상 카테고리 전체에서 고른다.

API와 DB

7. 광고 조회 1회에 실린 광고마다 served_count가 1 오른다. 실리지 않은 광고는 그대로다.
8. 같은 날 여러 번 조회하면 같은 행이 오르고, 날짜가 바뀌면 새 행이 생긴다(AD_STATS_TZ 기준).
9. on_map: 같은 place_id의 db 핀이 있으면 true, 그 핀을 지우면 false. 같은 kakao_place_id의 실시간 핀이 있어도 true.
10. 구성원이 아니면 조회와 클릭 기록 모두 404다.
11. 응답에 memo, 집계 값이 없다.
12. 집계 테이블에 user_id, map_id 칸이 없다.
13. 응답 헤더 Cache-Control: no-store

경계

14. recommend 모듈의 어떤 파일도 ads를 import하지 않는다(integration/test_import_rules.py에 추가).
15. 광고 장소를 지도에 올린 핀은 origin = direct이고, 직접 찍은 핀과 응답 모양이 같다(source: search에 광고 응답의 값을 그대로 보냄).
16. 광고를 등록해도 places.can_recommend 값이 바뀌지 않는다.

## 12. 작업 나누기

| 담당 | 일 | 이슈 |
|---|---|---|
| 루트 | 10절 문서, api-spec, contracts 목 서버, 계약 테스트 목록 | #642 |
| backend/places | `places.api.get_ad_places` | #645 |
| backend/recommend | `recommend.api.latest_run_place_ids` | #646 |
| backend/pins | `pins.api.list_live_kakao_ids_on_map` | #647 |
| backend/ads | 테이블과 마이그레이션, 선택 규칙, 7.1과 7.2, 관리 스크립트, 테스트 | #648 |
| frontend | 광고 영역과 광고 칸, 탭 열 때 조회, 카테고리 바꿀 때 재조회, 겹침 숨김, 클릭 기록, "이미 지도에 있어요", DESIGN.md 절 | #649 |

places, recommend, pins의 작은 함수 셋은 서로 의존하지 않고, ads가 셋 모두에 의존한다.

## 13. 남은 결정

기본값은 (제안)대로 문서에 넣었다. 다르게 가려면 이 표와 해당 절을 같이 고친다.

| 결정 | 기본값 |
|---|---|
| 1. 광고가 0개일 때 광고 영역을 숨길지 (4절) | 숨김 |
| 2. 클릭을 탭 한 번에 광고당 1회로 셀지 (4절) | 1회 |
| 3. 같은 장소에 active 광고를 하나만 둘지 (6절) | 하나만 |
| 4. AD_RADIUS_M 시작값 (5절) | 5000m로 결정(2026-10-19) |
| 5. 기획안에서 v1과 v2 중 어디에 둘지 (10절) | v2로 결정(2026-10-19) |
