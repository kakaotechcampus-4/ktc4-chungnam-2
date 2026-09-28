# 선호(soft) 태그 매핑 초안

**이 문서는 초안이며 `docs/constraints.md`에 정식 등록되려면 루트 승인이 필요하다.**
여기 적힌 태그는 `backend/llm` 안에서만 쓰는 작업용 메모이고, 정본은 어디까지나
`docs/constraints.md`(fact_key 레지스트리)와 `backend/llm/schemas.py`(`FactKey`)다.

> **2026-09-21 (#99) — 배점 열을 제거했다.** ③-b 선호 순위가 코드로 옮겨가면서
> `RANK_CANDIDATES_PROMPT`에 박혀 있던 배점(quiet 3점, 나머지 2점)이 폐기됐다.
> 지금 점수 규칙은 `docs/constraints.md`의 "선호 점수 계산 (③-b)"에 있고, 라벨마다
> 가중치를 두지 않는다 — 히트당 (지지 구성원 수 − 반대 구성원 수)만큼 가산할 뿐이다.
>
> 그래서 이 문서에 남은 가치는 **매핑 예시 표현**이다. ②(`plan_evidence`)가 자유 텍스트를
> `fact_key`로 정규화할 때 참고한다. 이 정규화가 흔들리면 그 뒤 점수 계산이 아무리
> 정확해도 소용이 없으므로, 오히려 ③-b가 코드로 간 지금 더 중요해졌다.

## 공식 레지스트리 태그 (docs/constraints.md + schemas.py FactKey에 이미 있음)

| `fact_key` | 뜻 | 매핑 예시 표현 |
|---|---|---|
| `quiet` | 조용함 | "조용한 곳이면 좋겠어요", "시끄럽지 않게" |
| `wait_short` | 대기 짧은 곳 | "웨이팅 짧은 데로", "바로 들어갈 수 있는 곳" |
| `comfortable_seat` | 좌석이 편함 | "의자가 편했으면", "오래 앉아있기 좋은 곳" |
| `local_flavor` | 지역색 있는 곳 | "그 동네다운 곳", "여기서만 먹을 수 있는 거" |

## 제안 중 (공식 레지스트리 밖)

- **`taste_good`** — 제안 중. 아직 `docs/constraints.md` 공식 레지스트리에도, `schemas.py`의
  `FactKey`에도 없다. 루트 승인 전까지는 프롬프트에 반영하지 않는다.
