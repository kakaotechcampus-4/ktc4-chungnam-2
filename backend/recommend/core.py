"""
기능형 코어 — 순수 함수만 둔다(docs/code-quality.md). DB·게이트웨이를 건드리지 않고,
이미 로드된 값을 받아 판정만 한다.

멤버십·작성자(author) 판정은 여기 두지 않는다 — authz.resolve_principal(gateway 호출, I/O)와
authz.can()이 이미 그 판정을 갖고 있어(authz/policy.py::AUTHOR_CONSTRAINED_ACTIONS에
recommend.publish가 등록됨) 여기서 다시 만들지 않는다(flows.py 모듈 docstring 참고 —
mentor-review-plan.md의 원래 계획은 이 판정도 이 함수(check_publishable)에 넣으라고
했지만, 그 계획이 전제한 pins.ports.MembershipGateway.is_member()는 PR #71로 이미
삭제됐다). 이 파일에 남는 건 candidate/run 자체의 상태 판정뿐이다.
"""

from common.errors import AppError
from recommend.models import RecommendRun


def check_run_ready(run: RecommendRun) -> None:
    """run.status가 'done'이 아니면 409 NOT_READY.

    done이 아닌 나머지 상태(collecting_evidence/awaiting_region_confirm/executing/failed)를
    전부 동일하게 취급한다 — mentor-review-plan.md 실패 매핑 표는 "run이 아직 완료 안 됨"
    하나로만 다뤘다. failed를 다른 코드로 구분할지는 이 계획 범위 밖의 결정이라 루트 확인이
    필요하다(for_Root.md에 기록)."""
    if run.status != "done":
        raise AppError("NOT_READY")
