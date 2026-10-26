# 배포 절차

코드를 올리는 것만으로 끝나지 않는 단계를 적는다. 데이터 적재, 재계산, 예약 실행, 환경 변수처럼 코드 밖에서 맞춰야 하는 것이다. 이 단계가 문서에 없으면 새 코드가 옛 데이터 위에서 돈다(멘토 리뷰 #680: 옛 규칙으로 계산된 `can_recommend`가 남아 정예가 아닌 13만여 곳이 추천 후보였다, #743).

## 이 문서를 고치는 규칙

- 코드 밖 단계를 새로 만들거나 바꾸는 PR은 이 문서를 같은 PR에서 고친다. 적재 명령, 재계산, 예약 실행, 새 환경 변수가 모두 해당한다.
- 같은 값을 두 곳에 저장해서 재계산 단계가 생기면, 먼저 저장한 칸을 없애고 원본을 바로 읽을 수 있는지 본다(#743). 재계산 단계는 그래도 필요할 때만 둔다.
- 확인되지 않은 것은 "미정"이나 "아직 없음"으로 적고 이슈 번호를 단다.

## 지금 상태

- 배포 환경은 아직 정하지 않았다. Dockerfile과 Cloud Run 설정이 저장소에 없다(#168). 방향은 `docs/architecture.md` 6절이다(main 병합 시 Cloud Run).
- 서버는 인스턴스 하나를 전제로 한다. 서버가 시작할 때 진행 중으로 남은 AI 코스 run을 모두 끝낸다(`agent.course.service.interrupt_unfinished_runs`). 인스턴스가 둘 이상이면 새 인스턴스가 옛 인스턴스에서 아직 도는 run을 끊는다. 늘리기 전에 #168에서 작업 큐(Cloud Tasks)를 정한다.

## 배포할 때마다

순서대로 한다.

1. 환경 변수를 맞춘다. 키 목록은 `backend/.env.example`이다(DATABASE_URL, REDIS_URL, KAKAO_CLIENT_ID, KAKAO_CLIENT_SECRET, KAKAO_REDIRECT_URI, FRONTEND_BASE_URL, FRONTEND_LOGIN_REDIRECT_URL, SESSION_SECRET, PINGO_ENV, CORS_ALLOW_ORIGINS, PLACES_MODE, ELICE_ML_API_BASE_URL, ELICE_ML_API_KEY, LLM_MODE). 배포는 `PINGO_ENV=prod`다. 값은 저장소나 채팅에 남기지 않는다. 새 키를 더한 PR은 이 목록도 고친다.
2. 마이그레이션을 올린다: `python -m alembic upgrade head`(backend에서). head는 하나여야 하고 CI(backend-test)가 같은 명령으로 확인한다.
3. 코드를 배포한다.
4. 아래 "데이터가 바뀔 때"에 해당하는 단계가 이번 배포에 있는지 확인한다.

## 데이터가 바뀔 때

| 단계 | 언제 | 명령 | 주의 |
|---|---|---|---|
| 장소 적재 | 처음 한 번, 정예DB 공유본이 새로 나왔을 때 | 아래 "장소 데이터 적재" 순서 전체 | 정예를 먼저 `--authoritative`로, 커버리지(인허가)는 그다음. 끝에 나오는 `[curated] 분류별 정예 / 정예 아님` 수를 확인한다 |
| 영업시간(`place_hours`) | 장소 적재 뒤, 정예 라벨이 바뀌었을 때 | `python -m places.load place-hours --file <라벨 JSON>` | 장소를 먼저 넣는다(못 찾은 장소는 건수만 보고한다). 칸이 없는 장소는 행을 만들지 않고, 영업 여부는 "확인 필요"로 통과한다. 추천(「영업 종료 제거」)과 AI 코스(휴무 요일)가 함께 읽는다(#747) |
| 광고 | 광고를 넣거나 뺄 때 | `python -m ads.scripts.register --csv <경로>`, `python -m ads.scripts.deactivate <ad_id>` | `docs/ads.md`. 광고는 추천 후보 여부(`curated`)를 바꾸지 않는다. 장소를 새 DB에 다시 넣으면 장소 id가 바뀌므로 광고도 다시 등록한다 |

추천 후보 여부는 재계산할 것이 없다. 후보 조회가 `places.curated`를 바로 읽는다(#743). 정예가 늘면 정예 적재만 하면 된다.

### 장소 데이터 적재

지금 데이터는 정예DB 공유본 2026-10-25판이다(서울, 그리고 v2 범위인 대전, 춘천, 광주, 대구, 부산). 폴더는 저장소 밖에 둔다. 명령은 `backend`에서 돌리고, 윈도는 먼저 `PYTHONUTF8=1`을 켠다. 공유본 안의 `README.md`가 명령의 정본이고, 아래는 그 순서를 옮긴 것이다.

1. 새 공유본으로 바꿀 때는 새 DB에서 시작한다. 로더는 파일에서 빠진 장소와 라벨을 지우지 않는다(공유본 `서울/README.md` "적재만으로는 지워지지 않는 것"). 새 DB를 만들고 `python -m alembic upgrade head`를 먼저 한다.
2. 서울 정예: `restaurants`, `cafes`, `tourapi` 순서로 `--authoritative --file <장소> --labels <라벨>`. 관광지 라벨은 JSON이 아니라 CSV다. 음식점 다음에 카페를 넣어 두 파일에 겹치는 6곳을 카페로 둔다(#507).
3. 서울 커버리지: `permit --encoding cp949`에 인허가 파일 3개를 `--file`로 한 번에 준다. 이어서 `restaurant-labels --file permit_cover_labels.json`.
4. 지역마다(v2): 2와 3을 `--all-regions`를 붙여 같은 순서로 한다(`restaurant-labels`에는 붙이지 않는다).
5. 영업시간: 장소를 모두 넣은 뒤 `place-hours`. 서울은 음식점 라벨 JSON, 카페 라벨 JSON, 관광지 `tourist_seoul_closed_days.json`. 지역은 음식점, 카페, 관광지 라벨 JSON에 `--all-regions`.

- 모든 명령은 `--dry-run`을 지원한다. 처음 한 명령은 dry-run으로 경로와 건수를 확인한다.
- 기존 DB를 유지한 채 인허가만 새로 받을 때 `permit --close-missing`을 쓴다(파일에 없는 커버리지를 폐업으로 바꾼다). 지역 커버리지에 쓰면 서울 커버리지가 닫히지 않는지 먼저 `--dry-run`으로 본다. 새 DB에서는 닫을 행이 없어 쓰지 않는다.
- 2026-10-27 로컬 실측(새 DB, 서울과 5개 지역 전부): 장소 199,211곳(정예 13,901), 라벨 약 191만 건, 영업시간 12,843곳.

## 예약 실행

| 작업 | 명령 | 주기 | 상태 |
|---|---|---|---|
| 정기 정리: 지도(삭제 30일 후), 알림(90일), 게스트(90일 미사용) | `python -m maintenance.run` | 미정(하루 한 번을 제안) | 스케줄러 미정(#168) |
| v2 계획 보조 에이전트 관찰 | `POST /internal/agent/tick` | 5분(`docs/agent-v2.md` 12.1) | 엔드포인트와 예약 모두 아직 없음(#535). 개발과 시연은 `AGENT_LOOP_IN_PROCESS=1`로 서버 안에서 돈다 |
| agent 일일 정리 | 없음 | 서버 안에서 돈다 | 따로 예약하지 않는다(`backend/maintenance/CLAUDE.md`) |

## 배포 전에 정할 것

- `event_log` 오래된 행 삭제: 읽기는 24시간으로 자르지만(`realtime.service.RETENTION`) 지우는 작업은 아직 없다. `created_at` 인덱스는 삭제용으로 있다. 정기 정리(`maintenance.run`)에 단계로 넣을지 정한다.
- 배포 환경, 비밀 관리, 프리뷰 배포(#168).
- 관찰 tick 엔드포인트와 예약(#535).
- 개발 중 로컬 DB에 쌓인 카카오 좌표와 이름은 배포 전에 지운다(`docs/architecture.md`, #53). 배포 DB를 로컬 DB에서 복사하지 않는다.
