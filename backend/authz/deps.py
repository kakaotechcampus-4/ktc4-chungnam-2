"""
FastAPI 의존성 배선. maps(#19)가 아직 없어, 그 자리를 채우는 개발용 어댑터를 여기 둔다 —
이름에 "아직 진짜가 아니다"가 드러나게 해서 나중에 교체를 잊지 않게 한다(backend/pins/deps.py와
같은 패턴). maps가 준비되면 이 파일의 Depends 대상만 바꾸면 된다.

authz는 HTTP 라우터가 없으므로(이 모듈은 다른 모듈이 호출하는 라이브러리다) 여기 배선은 authz
자신의 테스트, 그리고 향후 다른 모듈의 router.py가 가져다 쓰는 용도다.

get_membership_gateway는 common.adapters.select()를 거친다 — settings.membership_mode가
"real"인데 실구현이 없으면(maps #19 전까지는 항상 그렇다) 여기서 ConfigError로 죽는다.
prod에서 이 개발용 어댑터가 선택되는 것도 select()가 막는다(Settings.__post_init__과
select() 양쪽에서 이중으로 걸린다 — common/adapters.py 참고).
"""

from fastapi import Depends

from authz.policy import Role
from authz.ports import MembershipGateway
from common.adapters import select
from common.settings import settings


class AllowAllMembership:
    """maps(#19) 전까지 쓰는 개발용 어댑터 — 항상 'member'로 취급한다.

    owner 전용 액션(map.settings.edit, member.kick)은 이 스텁으로는 절대 열리지 않고, 비구성원
    (role=None) 경로도 이 스텁으로는 절대 밟히지 않는다 — 그 두 경로는 이 어댑터로는 수동 확인이
    불가능하므로 authz/tests가 Principal을 직접 만들어 덮는다."""

    def get_role(self, map_id: str, user_id: str) -> Role | None:
        return "member"


def _dev_membership() -> AllowAllMembership:
    return AllowAllMembership()


get_membership_gateway = select(
    "authz.MembershipGateway", settings.membership_mode,
    {"dev": _dev_membership, "real": None}, "maps #19",
)


MembershipGatewayDep = Depends(get_membership_gateway)
