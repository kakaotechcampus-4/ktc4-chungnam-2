# 2026-11-04 「핑고 AI 조언」 시연 지도 — 로컬 확인 (#1301)

로컬 서버를 `PINGO_ENV=staging`으로 띄워(`pingo_eval`, develop a099c2b8, 실제 모델 gpt-6-luna) `qa/harness/seed_agent_demo.py`를 HTTP로 돌렸다. 발표자는 QA 로그인 사용자로 대신했다. 작업 기록(#1305)과 살펴본 상태는 이 develop에 아직 없어 보지 않았다.

| 시나리오 | 결과 |
|---|---|
| stall (1회차, `--tick` 한 번) | 지도가 관찰 차례에 들지 않음 — 로컬 DB에 차례인 지도가 22곳이고 tick은 6곳씩 본다(`TICK_MAX_MAPS`). 새 지도는 `next_check_at`이 비어 순서가 뒤다. 3번째 tick에 관찰됨 → `--tick`을 제안이 뜰 때까지 반복(최대 8번)으로 고침 |
| stall (2회차) | tick 1번 만에 제안. 신호 stall(음식점, trigger=activity), 도구 기록 preview_filter → get_reasons → get_readiness → web_check. 화면: 현황 문단 「…출발이 7일 남았으니 음식점부터 보면 좋겠어요」, 제목 「음식점 후보가 반대 의견 뒤로 멈춰 있어요」, 「지금 맞는 곳이 47곳 있어요」, 버튼 「음식점 추천 받기」, 우리 데이터 2줄(매운맛 전문·대기가 짧은 곳 모름, 웹 확인 not_found), 우리 조건 요약 must_keep 2 |
| split (1회차) | 출력이 파이프에서 끝날 때 한꺼번에 나와 발표자가 초대 링크를 볼 수 없었다 → 줄 단위 출력으로 고침(스테이징의 `docker compose exec -T`도 같다) |
| split (2회차) | 발표자 입장 → QA 둘의 ♥·🚫 → 발표자 ♥ → tick 1번 만에 제안. different_axes(♥ 조용한 곳 / 🚫 주차 가능), 「주차가 가능하고 조용한 곳을 함께 조건으로 보면 맞는 곳이 19곳 있어요」, 버튼 「카페 추천 받기」 |

본 문제: 인용이 「「…」」로 겹친다(#767 1번, diagnose-v5 후속). G01~G06은 #1305·#1300이 스테이징에 올라간 뒤 화면으로 돌린다.
