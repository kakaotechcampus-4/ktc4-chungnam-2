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
| 장소 적재 | 처음 한 번, 정예 납품본이나 인허가 데이터가 바뀔 때 | `python -m places.load ...` 순서 전체(`docs/team-setup-guide.md` 5-4, `docs/openapi-workflow.md`) | 정예를 먼저 `--authoritative`로, 커버리지(인허가)는 그다음. 다시 넣을 때도 순서 전체를 처음부터 한다(#507). 끝에 나오는 `[curated] 분류별 정예 / 정예 아님` 수를 확인한다 |
| 영업시간(`place_hours`) | 영업시간 데이터를 받았을 때 | 아직 없음(#690) | 테이블은 마이그레이션 0038이 만든다. 행이 없으면 영업 여부는 "확인 필요"로 통과한다 |
| 광고 | 광고를 넣거나 뺄 때 | `python -m ads.scripts.register --csv <경로>`, `python -m ads.scripts.deactivate <ad_id>` | `docs/ads.md`. 광고는 추천 후보 여부(`curated`)를 바꾸지 않는다 |

추천 후보 여부는 재계산할 것이 없다. 후보 조회가 `places.curated`를 바로 읽는다(#743). 정예가 늘면 정예 적재만 하면 된다.

## 예약 실행

| 작업 | 명령 | 주기 | 상태 |
|---|---|---|---|
| 정기 정리: 지도(삭제 30일 후), 알림(90일), 게스트(90일 미사용) | `python -m maintenance.run` | 미정(하루 한 번을 제안) | 스케줄러 미정(#168) |
| v2 계획 보조 에이전트 관찰 | `POST /internal/agent/tick` | 5분(`docs/agent-v2.md` 12.1) | 엔드포인트와 예약 모두 아직 없음(#535). 개발과 시연은 `AGENT_LOOP_IN_PROCESS=1`로 서버 안에서 돈다 |
| agent 일일 정리 | 없음 | 서버 안에서 돈다 | 따로 예약하지 않는다(`backend/maintenance/CLAUDE.md`) |

## 배포 전에 정할 것

- `event_log` 오래된 행 삭제: 읽기는 24시간으로 자르지만(`realtime.service.RETENTION`) 지우는 작업은 아직 없다. `created_at` 인덱스는 삭제용으로 있다. 정기 정리(`maintenance.run`)에 단계로 넣을지 정한다.
- 영업시간 적재 명령(#690).
- 배포 환경, 비밀 관리, 프리뷰 배포(#168).
- 관찰 tick 엔드포인트와 예약(#535).
- 개발 중 로컬 DB에 쌓인 카카오 좌표와 이름은 배포 전에 지운다(`docs/architecture.md`, #53). 배포 DB를 로컬 DB에서 복사하지 않는다.
