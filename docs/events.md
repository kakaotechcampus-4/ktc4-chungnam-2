# 실시간 이벤트 스키마 (SSE)

작성 기준: `docs/architecture.md` 4절(D6 — SSE 확정) + 최종기획안 4절, 5-5-1
전송 방향: 클라이언트→서버는 일반 HTTP(`api-spec.yaml`), 서버→클라이언트만 SSE. 멘토: "클라이언트→서버 빈도가 매우 적어서 웹소켓보다 더 간단한 방식으로 충분."

## 채널 2개

| 채널 | 엔드포인트 | 구독 대상 | 용도 |
|---|---|---|---|
| 전체(public) | `GET /maps/{mapId}/events` | 지도의 모든 구성원 | 게시된 핀·반응·확정 리스트 변화 |
| 개인(private) | `GET /maps/{mapId}/events/me` | 요청자 본인만 | 본인의 비공개 AI 후보, run 진행 상태 (5-5-1) |

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
| `shortlist.changed` | `{ item: ShortlistItem, action: 'added'\|'removed' }` | 확정 리스트 변경 |
| `route.recalculated` | `Route[]` | 확정 리스트 변경 시 즉시 재계산 결과 (5-10, 재계산 버튼 없음) |
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

## 열린 항목

- `event_log` 보존기간 (재동기화 폴백 임계값)
- 개인 채널 다중 탭 처리 (같은 사용자가 여러 탭을 열었을 때 중복 구독)
