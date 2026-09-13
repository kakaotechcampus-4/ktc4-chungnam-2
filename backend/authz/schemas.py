"""
docs/api-spec.yaml의 Permissions 스키마와 1:1 (components/schemas/Permissions).
Pin·EvidenceLine·ShortlistItem 3개 리소스가 공유하는 스키마라 authz가 소유한다 — pins/schemas.py에도
동명의 모델이 있지만(#56 이관 전까지), 그건 pins가 아직 이 모듈을 안 쓰기 때문일 뿐이다.

스펙에 required가 없고, 리소스 종류마다 의미 있는 필드가 다르므로(예: can_disable은
evidence_line 전용) 전부 optional로 둔다 — 호출부의 response_model_exclude_none=True가
의미 없는 필드를 응답에서 걷어낸다.
"""

from pydantic import BaseModel


class Permissions(BaseModel):
    can_react: bool | None = None
    can_revert: bool | None = None
    can_add_to_shortlist: bool | None = None
    can_remove_from_shortlist: bool | None = None
    can_disable: bool | None = None  # evidence_line 전용: 자기가 쓴 것만 true
    can_delete: bool | None = None
