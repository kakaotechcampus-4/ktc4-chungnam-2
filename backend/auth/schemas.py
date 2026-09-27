"""
CurrentUser는 docs/api-spec.yaml의 /auth/* 응답 스키마와는 별개다 — 이건 인증 결과로 다른
모듈에 넘기는 내부 산출물이다(mentor-review-plan.md 참고).

UserResponse는 반대로 계약용이다 — api-spec.yaml의 User 스키마(id, display_name)와 1:1.
"""

from dataclasses import dataclass

from pydantic import BaseModel


@dataclass(frozen=True)
class CurrentUser:
    """인증이 만들어내는 유일한 산출물. 지금은 user_id뿐이지만, 세션에 값이 붙어도
    (display_name, session_id) 호출부 시그니처가 바뀌지 않게 객체로 둔다."""

    user_id: str


class UserResponse(BaseModel):
    """GET /auth/me 응답 — docs/api-spec.yaml의 User 스키마 그대로."""

    id: str
    display_name: str
