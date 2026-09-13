# 선호(soft) 태그 배점 초안

**이 문서는 초안이며 `docs/constraints.md`에 정식 등록되려면 루트 승인이 필요하다.**
여기 적힌 배점·태그는 `backend/llm` 안에서만 쓰는 작업용 메모이고, 정본은 어디까지나
`docs/constraints.md`(fact_key 레지스트리)와 `backend/llm/schemas.py`(`FactKey`)다.

배점은 코드가 아니라 ③-b 프롬프트에 고정 텍스트로 내장됨(`backend/llm/prompts.py`의
`RANK_CANDIDATES_PROMPT`).

## 공식 레지스트리 태그 (docs/constraints.md + schemas.py FactKey에 이미 있음)

| `fact_key` | 뜻 | 매핑 예시 표현 | 배점 |
|---|---|---|---|
| `quiet` | 조용함 | "조용한 곳이면 좋겠어요", "시끄럽지 않게" | 3 |
| `wait_short` | 대기 짧은 곳 | "웨이팅 짧은 데로", "바로 들어갈 수 있는 곳" | 2 |
| `comfortable_seat` | 좌석이 편함 | "의자가 편했으면", "오래 앉아있기 좋은 곳" | 2 |
| `local_flavor` | 지역색 있는 곳 | "그 동네다운 곳", "여기서만 먹을 수 있는 거" | 2 |

## 제안 중 (공식 레지스트리 밖)

- **`taste_good`** — 제안 중. 아직 `docs/constraints.md` 공식 레지스트리에도, `schemas.py`의
  `FactKey`에도 없다. 루트 승인 전까지는 실제 프롬프트(`RANK_CANDIDATES_PROMPT`)에
  반영하지 않는다.
