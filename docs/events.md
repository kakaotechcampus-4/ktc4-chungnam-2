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
| `pin.created` | `Pin` (api-spec.yaml) | 핀 생성 직후. `visibility=private`인 핀은 이 채널에 보내지 않는다 |
| `pin.published` | `Pin` | 「지도에 올리기」 실행 시 (5-5-1) |
| `pin.deleted` | `{ pin_id }` | 핀 삭제 |
| `reaction.changed` | `{ pin_id, reaction_summary }` | 반응 등록/수정/삭제 |
| `shortlist.changed` | `{ item: ShortlistItem, action: 'added'\|'removed'\|'reordered' }` | 확정 리스트 변경. `reordered`는 수동 정렬 (#30) |
| `route.recalculated` | `Route[]` | **「동선 짜주기」 실행 시** (#30, `POST /maps/{mapId}/route`). 확정 리스트 변경만으로는 발행하지 않는다 |
| `member.joined` | `Member` | 초대 수락 |
| `member.presence` | `{ user_id, online }` | 접속 상태 변화 |

### 개인 채널

| type | 페이로드 | 발생 시점 |
|---|---|---|
| `run.progress` | `{ run_id, step: 1..8, label }` | 추천 8단계 진행 (3절, 6절 "8단계 진행 표시") |
| `run.candidates_ready` | `{ run_id, candidates: Candidate[] }` | ④ 반영 — 점선 핀이 본인에게만 뜨는 시점 |
| `run.failed` | `{ run_id, error: Error }` | 추천 실패 (6절 "추천 실패" 화면) |

## 페이로드 봉투

```json
{
  "id": 10234,              // = seq, SSE id 필드와 동일
  "event": "pin.published",
  "data": { "...": "..." }
}
```

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
