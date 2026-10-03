"""
CurrentUser는 docs/api-spec.yaml의 /auth/* 응답 스키마와는 별개다 — 이건 인증 결과로 다른
모듈에 넘기는 내부 산출물이다(mentor-review-plan.md 참고).

UserResponse는 반대로 계약용이다 — api-spec.yaml의 User 스키마(id, display_name)와 1:1.
"""

from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, StringConstraints


@dataclass(frozen=True)
class CurrentUser:
    """인증이 만들어내는 유일한 산출물. 지금은 user_id뿐이지만, 세션에 값이 붙어도
    (display_name, session_id) 호출부 시그니처가 바뀌지 않게 객체로 둔다."""

    user_id: str


class UserResponse(BaseModel):
    """GET /auth/me 응답 — docs/api-spec.yaml의 User 스키마 그대로."""

    id: str
    display_name: str


class UserUpdateRequest(BaseModel):
    """PATCH /auth/me 요청 — api-spec.yaml의 UserUpdateRequest(1~50자). 앞뒤 공백을 먼저
    걷어낸 뒤 길이를 재므로 공백만 든 값은 빈 값과 같이 422가 된다."""

    display_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
