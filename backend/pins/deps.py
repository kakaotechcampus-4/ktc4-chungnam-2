"""FastAPI 의존성 배선 — DB 세션뿐이다.

membership·이벤트 발행·인증은 각각 authz.guard(+authz.deps)·common.events.record_event·auth.deps로,
장소 조회는 places.api 공개 함수(핀 생성은 match_place·record_kakao_match, #195)로 직접 간다.
"""

from fastapi import Depends

from common.database import get_db_session  # noqa: F401 — loaders.py·테스트가 pins.deps에서 가져온다

DbSession = Depends(get_db_session)
