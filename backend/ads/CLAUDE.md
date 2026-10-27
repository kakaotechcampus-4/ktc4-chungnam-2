# backend/ads

추천 탭 광고. **명세 `docs/ads.md`를 먼저 끝까지 읽는다.** 그다음 루트 문서: `/CLAUDE.md`, `backend/CLAUDE.md`(백엔드 공통),
`docs/api-spec.yaml`(ads 태그 — 정본, 명세와 다르면 이쪽을 따르고 루트에 보고), `docs/data-model.md`(ads 절).

## 책임

- `ads`, `ad_daily_stats` 두 테이블(마이그레이션 0036)
- 광고 선택(core.py 순수 함수, 랜덤은 `random.Random` 주입) — `GET /maps/{mapId}/ads`, 실린 광고마다 served_count +1
- 클릭 기록 — `POST /ads/{adId}/clicks`
- 관리 스크립트 `scripts/`(등록, 내리기, 집계 SQL은 `scripts/README.md`)

## 하지 않는 것 (명세 2절)

- places 행을 만들거나 고치지 않는다. 광고 장소 정보는 `places.api.get_ad_places`로만 읽는다(카카오 응답 저장 금지, #53)
- 추천의 후보와 순위에 끼지 않는다. recommend는 ads를 import하지 않는다(`integration/test_import_rules.py`)
- 모델을 부르지 않는다. 반응과 실격 필터를 적용하지 않는다
- pins에 광고 흔적을 남기지 않는다. 「지도에 올리기」는 FE가 기존 핀 생성 API로 한다
- 집계에 user_id, map_id를 넣지 않는다. 클릭 본문의 map_id는 권한 확인에만 쓴다
- 새 권한 액션, 새 에러 코드를 만들지 않는다

## 다른 모듈

`places.api.get_ad_places`, `recommend.api.latest_run_place_ids`, `pins.api.list_place_ids_on_map`,
`pins.api.list_live_kakao_ids_on_map`만 부른다. 필요한 함수가 없으면 이슈로 요청한다(`backend/CLAUDE.md`).

## 테스트

`ads/tests/`. 명세 11절 1~16. 커밋하는 테스트는 끝나고 ads 테이블을 비운다(#594, `tests/conftest.py`의 `factory`).
