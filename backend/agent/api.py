"""
다른 모듈이 agent에 요청하는 공개 함수(docs/architecture.md 1절 — 다른 모듈의 데이터 변경은 그 모듈의 api.py만).
purge_map_data와 delete_by_user는 커밋하지 않는다(부르는 쪽 트랜잭션). advise_run은 요청 세션을 쓰지 않고 자기 짧은 세션을
열어 커밋한다 — 모델을 부르는 동안 연결을 잡지 않기 위해서다(docs/agent-v2.md 9절, 12.6).

연결(maps/purge.py의 PURGE_STEPS, auth/service.py의 withdraw_user)은 #512에서 한다.
"""

from collections.abc import Callable

from sqlalchemy.orm import Session

from agent import service
from agent.schemas import RunAdvice
from common.database import SessionLocal


def purge_map_data(db: Session, *, map_ids: list[str]) -> dict[str, int]:
    """지도 정리(maps.purge, #431)가 부른다 — 이 지도들의 agent_* 7개 테이블 행을 모두 지우고 테이블 이름 → 지운
    행 수를 돌려준다. 다른 모듈 테이블을 참조하지 않아서 PURGE_STEPS 어디에 둬도 된다. 커밋하지 않는다."""
    return service.purge_map_data(db, map_ids=map_ids)


def delete_by_user(db: Session, *, user_id: str, map_ids: list[str]) -> dict[str, int]:
    """탈퇴(auth.service.withdraw_user, #155)가 부른다 — `map_ids`에는 `maps.api.lock_member_maps`가 돌려준 지도
    목록을 넘긴다. 그 지도들의 우리 조건 요약을 지우고 agent_runs의 tool_calls·verification을 비운다. 그 사람의
    열람 기록은 지도와 무관하게 모두 지운다. 테이블 이름 → 지우거나 비운 행 수. 커밋하지 않는다.

    순서 제약은 없다(agent는 다른 모듈 테이블을 읽지 않는다). 반응 삭제 앞이든 뒤든 같은 결과다."""
    return service.delete_by_user(db, user_id=user_id, map_ids=map_ids)


def advise_run(
    run_id: str, requester_id: str, *, session_factory: Callable[[], Session] = SessionLocal,
) -> RunAdvice | None:
    """추천 막힘 조언(docs/agent-v2.md 9절, #587) — `GET /runs/{runId}/advice`(recommend 라우터 → recommend.flows)가 부른다.
    그 run의 요청자에게만 그 run의 데이터로 조언한다. 없는 run은 AppError NOT_FOUND, requester_id가 run 요청자가 아니면
    FORBIDDEN(라우터가 이미 막지만 한 번 더 본다). 대상이 아니거나(완료 전, 결과 3곳 이상이고 같은 카테고리 run 3개 미만)
    낼 조언이 없으면 None(204).

    run당 한 번 만들어 agent_run_advice에 저장하고(ON CONFLICT (run_id) DO NOTHING), 그 뒤로는 저장된 것을 돌려준다.
    session_factory로 짧은 세션을 여러 번 연다 — 조회, 모델 호출(세션 없음), 저장과 커밋. 모델은 Gateway(agent/deps.py)가 고른다."""
    # flows는 다른 모듈의 api를 여럿 불러오고, 그중 auth.service와 recommend.flows가 이 파일을 불러온다. 맨 위에서 불러오면
    # 고리가 생겨 여기서 불러온다 — 이 파일은 탈퇴와 지도 정리가 쓰는 가벼운 입구로 남는다.
    from agent import flows

    return flows.advise_run(run_id, requester_id, session_factory=session_factory)
