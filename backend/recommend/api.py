"""
다른 모듈이 recommend에 요청하는 공개 함수(docs/architecture.md 1절 — 다른 모듈의 데이터
변경은 그 모듈의 api.py만). 커밋하지 않는다(common/database.py get_db가 요청당 한 번 커밋).
"""

from collections.abc import Collection, Sequence
from datetime import datetime

from sqlalchemy.orm import Session

from common import categories
from recommend import constraints, core, deps, flows, service
from recommend.ports import PlaceFactsGateway, PlaceSearchGateway


def delete_evidence_lines_by_author(db: Session, *, user_id: str) -> int:
    """탈퇴용 — `user_id`가 쓴 근거 줄(모든 run)을 지우고 지운 개수를 돌려준다."""
    return service.delete_evidence_lines_by_author(db, user_id=user_id)


def delete_evidence_lines_by_author_in_map(db: Session, *, user_id: str, map_id: str) -> int:
    """지도 나가기용(maps, #369) — `user_id`가 그 지도의 run에 쓴 근거 줄만 지운다. run과 후보는 남긴다."""
    return service.delete_evidence_lines_by_author_in_map(db, user_id=user_id, map_id=map_id)


def last_run_at_by_category(db: Session, *, map_id: str) -> dict[str, datetime]:
    """agent 스냅샷(docs/agent-v2.md 12.7, #522)이 부른다 — 카테고리 → 그 지도에서 가장 최근 run의 created_at.
    run이 없는 카테고리는 키가 없다. **후보, 근거, 요청자는 돌려주지 않는다** — run은 요청자만 보는 비공개 데이터라
    agent는 "그 뒤에 run이 있었나"만 본다(명세 2절 2번). 읽기 전용, 커밋하지 않는다."""
    return service.last_run_at_by_category(db, map_id=map_id)


def latest_run_place_ids(db: Session, *, map_id: str, requested_by: str, category: str | None = None) -> set[str]:
    """추천 탭 광고(docs/ads.md 5절 2번, #646)가 부른다 — 요청자의 이 지도 최신 run의 후보 place_id. category가 있으면
    그 카테고리의 최신 run 하나, 없으면 카테고리마다 최신 run. 다른 구성원의 run은 보지 않는다. run이 없거나 추천 대상이
    아닌 카테고리(숙소·기타 — run이 생길 수 없다)면 빈 집합. 권한은 보지 않는다. 읽기 전용, 커밋하지 않는다."""
    if category is not None and category not in categories.recommendable():
        return set()
    return service.latest_run_place_ids(db, map_id=map_id, requested_by=requested_by, category=category)


def get_readiness(db: Session, *, map_id: str, category: str) -> dict:
    """agent의 반대 후 정체 진단(docs/agent-v2.md 6.2, 10절 get_readiness, #530)이 부른다 — 그 카테고리가 추천
    준비(⓪)를 통과했나. `{ready, answered_count, required_count}`, `GET /maps/{mapId}/recommend/readiness`의 한
    카테고리 값과 같다(같은 함수 flows.readiness_for_category). 권한은 보지 않는다(agent가 구성원 범위에서 부른다).
    추천 대상이 아닌 카테고리(숙소·기타)는 ValueError — 라우터 응답에도 그 키가 없다. 읽기 전용, 커밋하지 않는다."""
    if category not in categories.recommendable():
        raise ValueError(f"추천 대상이 아닌 카테고리: {category}")
    return flows.readiness_for_category(db, map_id=map_id, category=category)


def fact_labels() -> dict[str, str]:
    """agent 의견 갈림 분석의 축 이름(docs/agent-v2.md 6.3, #564)이 부른다 — fact_key → 근거 줄에 그리는 표시 이름
    ("quiet" → "조용한 곳"). `constraints.FACT_LABELS`의 사본이라 고쳐도 원본에 영향이 없다."""
    return dict(constraints.FACT_LABELS)


def demote_wanted_place_identity(category: str, lines: Sequence[dict]) -> list[dict]:
    """agent structure_reasons(docs/agent-v2.md 10절, #564)가 부른다 — 추천 근거 조립과 같은 #422 규칙(🚫 사유 안의
    음식 종류 "원함"은 preferred). lines는 `{fact_key, wants, badge}`(다른 키는 그대로 둔다). 원본은 바꾸지 않는다."""
    return core.demote_wanted_place_identity(lines, category)


# ---- 추천 막힘 조언 전용(docs/agent-v2.md 9절, 10절, #585, #587) ----
# run은 요청자만 보는 비공개 데이터다(명세 2절 2번). 아래 다섯 함수는 권한을 판정하지 않는다 — agent가 run 요청자가
# 조언을 여는 사람인지 확인한 뒤 그 사람에게 그 run의 데이터로만 부른다. 없는 run은 AppError NOT_FOUND. 읽기 전용,
# 커밋하지 않는다.


def get_recent_runs(db: Session, *, run_id: str, limit: int = 10) -> list[dict]:
    """그 run과 같은 요청자, 같은 카테고리의 최근 run(그 run 포함), 최근순 — `[{run_id, status, result_count,
    created_at}]`. 지난 추천 기록(#469, service.list_runs_for_requester)을 그대로 쓴다. result_count는 후보 수이고
    done이 아니면 0이다. 권한 판정 없음(위 주석)."""
    run = service.get_run_or_404(db, run_id)
    return [
        {"run_id": str(row.id), "status": row.status, "result_count": candidate_count, "created_at": row.created_at}
        for row, candidate_count, _published_count in service.list_runs_for_requester(
            db, map_id=run.map_id, requested_by=run.requested_by, category=run.category, limit=limit,
        )
    ]


def get_run_meta(db: Session, *, run_id: str) -> dict:
    """그 run 자신의 정보 `{run_id, map_id, category, requested_by, status, result_count, created_at,
    default_radius_walk_min, widen_limit_walk_min}`(#587). agent가 조언 대상인지(완료, 결과 수)와 요청자 본인인지,
    반경 넓히기 상한(도보 30분, core.WIDEN_LIMIT_MIN)을 넘는 배율인지 본다. result_count는 get_recent_runs와 같은 기준(후보 수,
    done이 아니면 0). 권한 판정 없음(위 주석)."""
    run = service.get_run_or_404(db, run_id)
    return {
        "run_id": str(run.id), "map_id": run.map_id, "category": run.category, "requested_by": run.requested_by,
        "status": run.status, "result_count": _result_count(db, run), "created_at": run.created_at,
        "default_radius_walk_min": run.default_radius_walk_min, "widen_limit_walk_min": core.WIDEN_LIMIT_MIN,
    }


def get_run_funnel(db: Session, *, run_id: str) -> dict:
    """마지막 실행(execute/widen/retry)의 `{result_count, funnel, passed_count}` — simulate_filter의 before·after와 같은 모양.
    funnel은 저장한 깔때기 `[{label, removed_count}]`(recommend_runs.last_funnel) 그대로이고 「추천 가능 아님 제거」(#558) 단계도
    저장된 대로 들어 있다. result_count는 get_run_meta와 같은 기준(후보 수, done이 아니면 0), passed_count는 필터를 모두
    통과한 곳의 수(상위 3곳을 고르기 전, core.passed_count, #587). 실행 전이면 funnel []·0·0. 사본이라 고쳐도 행에 영향이
    없다. 권한 판정 없음(위 주석)."""
    run = service.get_run_or_404(db, run_id)
    funnel = [{"label": entry["label"], "removed_count": entry["removed_count"]} for entry in run.last_funnel or []]
    result_count = _result_count(db, run)
    return {"result_count": result_count, "funnel": funnel, "passed_count": core.passed_count(result_count, funnel)}


def get_run_evidence(db: Session, *, run_id: str) -> list[dict]:
    """그 run의 근거 줄 전부(비활성 포함) `[{line_id, text, badge, fact_key, wants, is_active, author_id, chip_id}]`, 근거
    줄 정본 순서(created_at, seq). 요청자 본인 줄인지는 agent가 author_id로 판단한다. chip_id(칩에서 나온 줄만, 아니면 None)는
    agent가 키 없는 줄 중 「비싸요」처럼 추천이 거르지 않는 줄을 가르는 데 쓴다(#587). 권한 판정 없음(위 주석)."""
    run = service.get_run_or_404(db, run_id)
    return [
        {
            "line_id": str(line.id), "text": line.text, "badge": line.badge, "fact_key": line.fact_key,
            "wants": line.wants, "is_active": line.is_active, "author_id": line.author_id, "chip_id": line.chip_id,
        }
        for line in service.list_evidence(db, str(run.id))
    ]


def simulate_filter(
    db: Session, *, run_id: str, radius_factor: float | None = None, disable_line_ids: Collection[str] = (),
    place_search: PlaceSearchGateway | None = None, place_facts: PlaceFactsGateway | None = None,
) -> dict:
    """실격 필터를 입력만 바꿔 다시 돌린다(flows.simulate_filter — 필터를 다시 구현하지 않는다). `{before, after}`,
    각각 `{result_count, funnel[{label, removed_count}], passed_count}`. passed_count는 필터를 모두 통과한 곳의 수(상위 3곳을
    고르기 전, #587)라 결과 수(최대 3)와 달리 조건을 바꾼 효과를 그대로 비교할 수 있다. before는 지금 저장된 지역·활성 근거 줄로 다시 돌린 값이라
    그 사이 바뀐 것이 없으면 마지막 실행 결과와 같다. after는 지역 반경에 radius_factor를 곱하고 disable_line_ids를
    비활성으로 본다. 이미 제안·거절한 곳은 실행 때와 같이 뺀다(가드레일 6). 라벨을 모르는 가게는 실행 때처럼
    통과라 실격 숫자는 라벨이 확실한 가게만 센다.

    장소 검색·라벨 Gateway는 생략하면 실행(라우터)과 같은 것을 고른다(recommend.deps, dev는 스텁). 쓰지 않는다 —
    run·후보·근거 줄·지역·제외 목록·last_funnel 모두 그대로다. 그 run의 근거 줄이 아닌 id는 NOT_FOUND, radius_factor가
    0 이하면 ValueError. 권한 판정 없음(위 주석)."""
    return flows.simulate_filter(
        db, run_id=run_id, radius_factor=radius_factor, disable_line_ids=disable_line_ids,
        place_search=place_search or deps.get_place_search_gateway(),
        place_facts=place_facts or deps.get_place_facts_gateway(),
    )


def _result_count(db: Session, run) -> int:
    return len(service.list_candidates(db, str(run.id))) if run.status == "done" else 0


def purge_map_data(db: Session, *, map_ids: list[str]) -> dict[str, int]:
    """지도 정리(maps.purge, #431)가 부른다 — 이 지도들의 evidence_lines·candidates·regions·exclusions·
    recommend_runs만 지우고 테이블 이름 → 지운 행 수를 돌려준다. 커밋하지 않는다."""
    return service.purge_map_data(db, map_ids=map_ids)
