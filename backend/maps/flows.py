"""
여러 모듈의 테이블을 한 커밋에서 바꾸는 기능 실행 함수(docs/architecture.md §1.1). 순서와 실패
처리만 한다 — 판단(후임 정하기, 나갈 수 있는가)은 maps/core.py에 있다. 커밋하지 않는다.
"""

from sqlalchemy.orm import Session

from common.errors import AppError
from common.events import record_event
from maps import core, service
from pins import api as pins_api
from recommend import api as recommend_api


def leave_map(db: Session, *, map_id: str, user_id: str) -> None:
    """지도 나가기(#369). 탈퇴 규칙(#155)을 이 지도 하나로 좁힌다 — 그 지도에 남긴 반응과 근거 줄만
    지우고, 핀·확정 리스트 항목·초대 링크·추천 run과 후보는 남긴다.

    maps 행을 먼저 잠근다(#369 13번). 잠근 뒤에 멤버십을 다시 읽어야 방장과 다음 사람이 동시에
    나갈 때 이미 나간 사람에게 방장이 넘어가지 않는다."""
    service.get_map_or_404(db, map_id, for_update=True)
    roster, withdrawn = service.roster_of(db, map_id)
    role = core.role_in(roster, user_id)
    if role is None:
        raise AppError("NOT_FOUND")  # 잠그는 사이 이미 나갔다
    new_owner = core.pick_successor(roster, withdrawn, user_id) if role == "owner" else None
    core.check_leave_allowed(role, new_owner)

    pins_api.delete_reactions_by_user_in_map(db, user_id=user_id, map_id=map_id)
    recommend_api.delete_evidence_lines_by_author_in_map(db, user_id=user_id, map_id=map_id)
    if new_owner is not None:
        service.transfer_owner(db, map_id=map_id, from_user_id=user_id, to_user_id=new_owner)
    service.remove_membership(db, map_id=map_id, user_id=user_id)
    record_event(db, core.member_left_event(map_id, user_id, new_owner))
