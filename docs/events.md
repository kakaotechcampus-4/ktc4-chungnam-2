# 실시간 이벤트 스키마 (SSE)

작성 기준: `docs/architecture.md` 4절(D6 — SSE 확정) + 최종기획안 4절, 5-5-1
전송 방향: 클라이언트→서버는 일반 HTTP(`api-spec.yaml`), 서버→클라이언트만 SSE. 멘토: "클라이언트→서버 빈도가 매우 적어서 웹소켓보다 더 간단한 방식으로 충분."

## 채널 2개

| 채널 | 엔드포인트 | 구독 대상 | 용도 |
|---|---|---|---|
| 전체(public) | `GET /maps/{mapId}/events` | 지도의 모든 구성원 | 게시된 핀·반응·확정 리스트 변화 |
| 개인(private) | `GET /maps/{mapId}/events/me` | 요청자 본인만 | 본인의 비공개 AI 후보, run 진행 상태 (5-5-1) |

두 경로 모두 `docs/api-spec.yaml`의 `realtime` 태그에 타입까지 있다 — `PublicEvent`/`PrivateEvent`가 이 문서의 이벤트 11종을 `oneOf`로 판별 유니온화한 것이다. 페이로드를 바꾸면 이 문서와 api-spec.yaml `Evt*` 스키마를 같이 고친다.

**채널 분리가 5-5-1을 구조적으로 강제한다.** "요청한 사람에게만 보인다"를 애플리케이션 로직의 if문이 아니라 애초에 그 사람만 구독 가능한 채널로 만든다 — 실수로 전체 채널에 흘려보내는 버그 자체가 나지 않는다.

## 이벤트 목록

모든 이벤트는 `event_log.seq`를 SSE의 `id:` 필드로 사용한다. 재연결 시 브라우저가 자동으로 `Last-Event-ID` 헤더를 보내고, 서버는 그 이후 이벤트만 재전송한다. `Last-Event-ID`가 없거나 너무 오래됐으면(`event_log` 보존기간 초과) 클라이언트는 `GET .../pins?since=` 등 REST 재조회로 폴백한다.

### 전체 채널

| type | 페이로드 | 발생 시점 |
|---|---|---|
| `pin.created` | `Pin` (api-spec.yaml) | 핀 생성 직후. v1은 private 핀 행이 없어 모든 핀이 이 채널로 나간다(비공개 후보는 핀이 아니라 개인 채널 `run.candidates_ready`로만 온다). 실시간 핀(`source=live`, #382)은 `lat`·`lng`·`place_name` 없이 `kakao_place_id`·`search_query`·`memo`만 실린다 — 받은 화면이 그 자리에서 위치를 다시 찾는다 |
| `pin.published` | `Pin` | 「지도에 올리기」 실행 시 (5-5-1) |
| `pin.deleted` | `{ pin_id }` | 핀 삭제 |
| `pin.updated` | `Pin` | 핀을 찍은 사람이 메모·분류를 고침(#466), 또는 구성원이 실시간 핀을 자체 DB 핀으로 승격함(#501 — `source`가 `live`→`db`, `place_id`·장소 값이 채워지고 반응·확정 항목은 그대로). `pin.created`와 같은 모양이다. 받은 FE는 그 핀을 갈아끼우고, 분류가 바뀌었으면 `FilterCounts`·readiness를 다시 불러온다 |
| `reaction.changed` | `{ pin_id, reaction_summary, user_id, display_name, type }` | 반응 등록/수정/삭제. `user_id`·`display_name`은 그 반응을 남긴(지운) 구성원, `type`은 `like`·`against`이고 삭제면 `null`이다(2026-10-04, FE 요청 — 「지우님이 반대 의견을 남겼어요」). 반응 내용(사유)은 싣지 않는다 |
| `shortlist.changed` | `{ item: ShortlistItem, action: 'added'\|'removed'\|'reordered' }` | 확정 리스트 변경. `reordered`는 수동 정렬 (#30) |
| `route.recalculated` | `Route[]` | **「동선 짜주기」 실행 시** (#30, `POST /maps/{mapId}/route`). 확정 리스트 변경만으로는 발행하지 않는다 |
| `member.joined` | `Member` | 초대 수락 |
| `member.left` | `{ map_id, user_id, new_owner_user_id \| null }` | 구성원이 지도에서 나감(#369). **방장이 계정을 탈퇴해 그 지도의 방장이 위임된 경우에도 보낸다**(`user_id`는 탈퇴한 사람, 2026-10-07 결정). 방장이 나가거나 탈퇴해 위임됐으면 `new_owner_user_id`에 새 방장, 아니면 null. 탈퇴했는데 넘길 사람이 없어 지도가 삭제되면 이 이벤트 대신 `map.deleted`만 보낸다. 받은 FE는 핀 목록(작성자 표시 포함), 핀 참여율, `FilterCounts`, readiness를 다시 불러온다. 나간 사람의 반응 삭제마다 따로 이벤트를 보내지 않는다 |
| `map.deleted` | `{ map_id }` | 방장이 지도를 삭제함(#369). 삭제와 같은 트랜잭션에 기록된다. realtime은 이미 연결된 구독자에게 이 이벤트를 보낸 뒤 연결을 닫는다(삭제된 지도는 새 구독이 404라 이 순서가 아니면 마지막 이벤트가 전달되지 않는다). 받은 FE는 내 지도 목록으로 돌아간다 |
| `map.updated` | `{ map_id, title, start_date, end_date, region? }` | 방장이 지도 제목·날짜·지역을 고침(#465). 수정과 같은 트랜잭션에 기록된다. 요청자 기준 값(`permissions` 등)은 싣지 않는다. 받은 FE는 지도 상세 캐시를 갱신한다 |
| `owner.changed` | `{ map_id, from_user_id, to_user_id }` | 방장이 직접 방장을 넘김(#468). 두 사람 모두 지도에 남는다 — **`member.left`를 재사용하지 않는다**(나간 것으로 오해해 SSE를 닫는다). 받은 FE는 지도 상세·구성원 목록(`role`)을 다시 불러온다 |
| `member.presence` | `{ user_id, online }` | 접속 상태 변화 — **v1 서버는 발행하지 않는다**(아래 「v1에서 발행하지 않는 이벤트」) |
| `agent.suggested` | `AgentSuggestion` (api-spec.yaml) | v2 계획 보조 에이전트가 지도 제안을 저장함(docs/agent-v2.md 15절). 지도당 동시에 하나. shadow 기간(`AGENT_SHADOW_MODE`)에는 발행하지 않는다 |
| `agent.resolved` | `{ suggestion_id, status, resolved_action_type }` | 제안이 끝남: 수락(accepted), 닫기(dismissed), 만료(expired), 무효화(superseded). 누가 처리했는지는 싣지 않는다 |
| `agent.summary_updated` | `AgentSummary` | 우리 조건 요약 갱신. 점이나 알림을 켜지 않는다 |
| `agent.settings_changed` | `{ enabled, updated_by }` | 구성원이 에이전트 모드를 켜거나 끔. 끄면서 제안이 있었으면 그 제안의 `agent.resolved`(superseded)도 함께 나간다 |

### 개인 채널

| type | 페이로드 | 발생 시점 |
|---|---|---|
| `run.progress` | `{ run_id, step: 1..8, label }` | 추천 8단계 진행 (3절, 6절 "8단계 진행 표시") — **v1 서버는 발행하지 않는다** |
| `run.candidates_ready` | `{ run_id, candidates: Candidate[] }` | ④ 반영 — 점선 핀이 본인에게만 뜨는 시점 |
| `run.failed` | `{ run_id, error: Error }` | 추천 실패 (6절 "추천 실패" 화면) — **v1 서버는 발행하지 않는다** |

### v1에서 발행하지 않는 이벤트 (2026-10-04)

- **`run.progress`·`run.failed`**: 추천 실행(`POST /runs/{id}/execute`·`/widen`·`/retry`)이 요청 안에서 동기로 끝나고, 이벤트는 요청 하나가 커밋될 때 한꺼번에 나간다 — 단계마다 보내도 끝에 한 번에 도착해 진행 표시가 되지 않고, 실패하면 트랜잭션이 롤백돼 `run.failed`도 저장되지 않는다. 그래서 v1에서는 보내지 않는다.
  - **진행 표시**는 프론트가 실행 요청이 돌아올 때까지(또는 결과 조회가 `done`이 될 때까지) 자체 애니메이션으로 보여 준다.
  - **실패**는 실행 요청의 HTTP 응답(500 `RECOMMEND_FAILED`, 상한이면 429 `RETRY_LIMIT` 등)으로 받는다. 이벤트를 기다리지 않는다.
  - 단계별 진행을 실시간으로 보여 주려면 실행을 백그라운드로 옮겨야 한다(v2 검토).
- **`member.presence`**: 접속 상태 추적이 없다. `Member.online`은 비어 온다 — 접속 점은 그리지 않는다.
- **`agent.*` 4종**: v2 계획 보조 에이전트(docs/agent-v2.md, #510)의 이벤트다. 계약만 먼저 올렸고 서버 구현 전이라 아직 발행되지 않는다. 목 서버는 보낸다. 구현 뒤에도 shadow 기간에는 발행하지 않는다.
- **FE는 이 이벤트들을 받아도 되지만 의존하지 않는다.** 결과는 항상 `GET /runs/{id}/result`가 정본이다(`done`이 될 때까지 2초 간격 조회).

## 이벤트별로 화면이 다시 받을 것 (#449)

FE는 이벤트를 받으면 아래 표대로 화면 데이터를 다시 받는다(캐시 무효화). 이벤트 페이로드로 바로 고칠 수 있는 것(핀 목록의 한 핀, 토스트)은 페이로드를 쓰고, 나머지는 다시 받는다. 이벤트나 화면 데이터를 추가할 때 이 표를 함께 고친다. 예전에는 핸들러마다 흩어져 있어 준비 상태와 구성원 목록이 빠졌다(멘토 리뷰).

| 이벤트 | 다시 받을 것 |
|---|---|
| `pin.created`, `pin.published` | 핀 목록(페이로드로 갱신), `GET /maps/{mapId}/counts` |
| `pin.updated` | 핀 목록의 그 핀(페이로드로 갱신 — 승격이면 이름·좌표가 새로 생기므로 지도 마커와 상세를 같이 갱신). 분류가 바뀌었으면 `GET /maps/{mapId}/counts`, `GET /maps/{mapId}/recommend/readiness` (#466) |
| `pin.deleted` | 핀 목록(페이로드로 갱신), `GET /maps/{mapId}/counts`, `GET /maps/{mapId}/recommend/readiness` |
| `reaction.changed` | 핀 목록의 그 핀(페이로드로 갱신), `GET /maps/{mapId}/counts`, `GET /pins/{pinId}/reactions`(열려 있으면), `GET /maps/{mapId}/recommend/readiness` |
| `member.joined` | `GET /maps/{mapId}`, `GET /maps/{mapId}/members` |
| `member.left` | `GET /maps/{mapId}/pins`, `GET /maps/{mapId}/counts`, `GET /maps/{mapId}`, `GET /maps/{mapId}/members`, `GET /maps/{mapId}/recommend/readiness` |
| `owner.changed` | `GET /maps/{mapId}`, `GET /maps/{mapId}/members`(방장 표시, #468) |
| `map.updated` | 지도 상세(페이로드로 갱신), `GET /maps`(내 지도 목록의 제목과 날짜, #465) |
| `map.deleted` | 지도 화면을 닫고 내 지도 목록(`GET /maps`)으로 |
| `shortlist.changed` | `GET /maps/{mapId}/shortlist`, `GET /maps/{mapId}/pins`(확정 핀 표시) |
| `route.recalculated` | 동선(페이로드 `Route[]`로 갱신, 또는 `GET /maps/{mapId}/route`) |
| `agent.suggested` | 에이전트 상태의 지금 제안(페이로드로 갱신). 시트가 열려 있으면 `POST /agent/suggestions/{id}/view`, 닫혀 있으면 점을 켠다 |
| `agent.resolved` | 지금 제안의 id가 같으면 비우고 점을 끈다(페이로드로 갱신) |
| `agent.summary_updated` | 그 카테고리 요약(페이로드로 갱신) |
| `agent.settings_changed` | 에이전트 상태의 모드(페이로드로 갱신). 변경자 표시 이름은 구성원 목록에서 찾는다 |

- 추천 준비 상태는 "♥나 🚫 의견이 달린 핀 1개"(#360)라 의견 하나, 핀 하나로 바뀐다. 그래서 반응과 핀 삭제에도 다시 받는다.
- 개인 채널의 `run.candidates_ready`는 결과 조회(`GET /runs/{id}/result`)가 정본이라 이 표와 상관없다(위 "v1에서 발행하지 않는 이벤트").

## 페이로드 봉투

```json
{
  "id": 10234,              // = seq, SSE id 필드와 동일
  "event": "pin.published",
  "data": { "...": "..." }
}
```

## 구독을 끊는 경우 (#369)

SSE 구독 권한(구성원인가)은 **구독을 시작할 때 한 번만** 본다. 그 뒤로는 지도 번호만 보고 이벤트를 보내므로, 구성원이 아니게 된 사람의 연결은 서버가 직접 끊어야 한다. 끊을 때도 **그 이벤트를 먼저 보내고 닫는다.** 받은 쪽이 왜 끊겼는지 알 수 있게 하기 위해서다.

| 이벤트 | 보낸 뒤 닫는 연결 |
|---|---|
| `map.deleted` | 그 지도의 모든 구독(전체 채널, 개인 채널) |
| `map.updated`, `owner.changed` | 그 지도의 모든 구독(전체 채널, 개인 채널) |
| `member.left` | 그 지도에서 `user_id`(나간 사람, 또는 탈퇴해 방장이 넘어간 사람)의 구독(전체 채널, 개인 채널). 다른 구성원의 연결은 그대로 둔다 |

- 그래서 전체 채널 구독도 누가 구독했는지(`user_id`)를 기억해야 한다. 지금은 개인 채널만 기억한다.
- 닫힌 뒤 같은 사람이 다시 구독하면 구독 시작 검사에서 404다(삭제된 지도, 또는 구성원이 아님). 다시 초대를 수락하면 새로 구독할 수 있다.
- 탈퇴했지만 방장이 아니었던 지도의 연결은 이 표에 없다. 그 지도에는 이벤트가 나가지 않는다(탈퇴 처리는 반응과 근거 줄만 지운다). 세션이 무효가 되므로 다음 재연결에서 401로 끊긴다.

## 전달 보장

1. **이벤트 행은 상태 변경과 같은 커밋에 들어간다.** 모든 모듈은 `common.events.record_event(db,
   event)`로 `event_log`에 행을 남기고, 커밋은 요청당 한 번 `common/database.py`의 `get_db`가
   한다. "DB는 바뀌었는데 이벤트는 안 나갔다"는 상태가 구조적으로 불가능하다 — 롤백되면 둘 다
   없다.
2. **전송은 커밋된 행을 읽어서 한다.** `realtime`이 `event_log`를 500ms 주기로 폴링해 구독 중인
   SSE 연결에 밀어준다. 모듈은 전송을 직접 호출하지 않는다.
3. **보장 수준은 at-least-once다.** 같은 이벤트가 두 번 도착할 수 있다(재연결 직후 겹침).
   클라이언트는 `id`(=seq)로 중복을 버린다 — 모든 페이로드는 멱등하게 적용 가능해야 한다
   (`pin.created`는 upsert, `reaction.changed`는 매번 집계 전체를 싣는다).
4. **`seq`는 커밋 순서와 다를 수 있다.** `bigserial`은 INSERT 시점에 번호를 배정하고 행은
   COMMIT 시점에야 보인다 — 동시 트랜잭션이 역순으로 커밋하면 `seq` 순서에 구멍이 생길 수
   있다. 폴러는 **연속된 앞부분만** 내보내고 구멍은 2초까지 기다린다(`realtime/core.py::advance`).
   2초가 지나도 안 채워지면 롤백된 트랜잭션이 태운 번호로 보고 건너뛴다 — 트랜잭션 실패도
   시퀀스를 소비하므로 구멍 자체는 정상이다. **재연결 재전송(`Last-Event-ID`) 경로는 대부분의
   경우 이 위험이 없다** — 재연결 시점엔 그보다 오래된 트랜잭션은 보통 이미 다 커밋되었거나
   종료됐기 때문이다. 다만 재연결 순간에 `last_seen`보다 낮은 `seq`를 이미 배정받은 트랜잭션이
   **아직 커밋 중**인 드문 경우는 재전송 쿼리에서도 같은 구멍이 보일 수 있다 — `realtime/
   service.py::replay`는 단순 `WHERE seq > after_seq` 조회이므로, 이 잔여 위험을 없애려면
   재전송도 `realtime/core.py::advance`와 같은 "연속 앞부분만" 로직을 통과시키거나(과할 수
   있음), 실용적으로는 그냥 무시한다 — 재전송은 폴러가 이미 한 번 처리한 뒤의 조회라 발생
   확률이 라이브 tail보다 훨씬 낮다. 실제로 문제가 관측되면 그때 `replay`에도 같은 로직을
   적용한다.
5. **보존기간 24시간.** `Last-Event-ID`가 24시간보다 오래됐거나 없으면 서버는 재전송하지 않고,
   클라이언트는 REST 재조회로 폴백한다(위 「이벤트 목록」). 이때 서버는 잘림 여부를 조용히
   넘어가지 않는다 — 재전송 스트림 맨 앞에 `event: control` / `data: {"type":
   "replay_truncated"}` 한 줄을 먼저 보내 클라이언트가 REST 재조회를 해야 한다는 걸 알게 한다.
6. **개인 채널 수신자.** `event_log.recipient_user_id`가 있는 행은 그 사용자의 개인 채널
   연결에만 간다. 전체 채널 쿼리는 `channel='public'`으로 고정돼 코드 레벨에서 섞이지 않는다.
7. **다중 탭.** 탭마다 별도 SSE 연결이고 각자 같은 이벤트 사본을 받는다. 서버는 탭을 구분하지
   않는다 — 3번의 멱등 적용 규칙이 이미 이걸 안전하게 만든다.
8. **v1 한계.** 폴러는 인스턴스 안 백그라운드 태스크다. Cloud Run은
   `--min-instances=1 --max-instances=1 --no-cpu-throttling`으로 띄운다. 인스턴스가 여러 개여도
   각자 폴링해 각자 구독자에게 보내므로 정합성은 깨지지 않지만, v1에서는 검증하지 않는다.
   PostgreSQL `LISTEN/NOTIFY`나 Redis pub/sub은 지연을 줄이는 다음 단계 후보로 남겨둔다(둘 다
   자체로는 durable하지 않아 폴링을 대체하지 못하고, 폴링 위에 얹는 최적화다).
