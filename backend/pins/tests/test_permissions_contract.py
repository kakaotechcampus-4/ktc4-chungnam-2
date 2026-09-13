"""
authz.core.permissions_for()가 pins 응답에 실제로 반영되는지 + 원래 pins/core.py::pin_permissions가
커버하던 3(kind)×2(role) 매트릭스 전체를 authz/tests/test_permissions.py의
test_pin_permissions_matches_pins_module 대신 여기서 재현한다(#56 이관, mentor-review-plan.md).

두 부분으로 나눈다 — GET /maps/{mapId}/pins는 요청자가 볼 수 있는 핀만 돌려주므로, "남의 private
핀에 대한 permissions"처럼 애초에 응답에 안 나오는 조합은 API 경로로 관측할 수 없다:
1. API 통합 테스트 — 실제로 응답에 나오는 조합만(kind별 shortlist 방향, 비구성원 404).
2. 직접 단위 테스트 — permissions_for(principal, Resource(...))를 kind×role 6개 조합 전부에
   직접 호출해, API 응답으로는 볼 수 없는 조합(비구성원 × 남의 private 핀 등)까지 포함한다.

이 파일이 통과한 다음에 authz/tests/test_permissions.py의
test_pin_permissions_matches_pins_module과 그 위 주석 블록을 지운다(순서 중요 — 커버리지 공백 방지).
"""

import uuid

import pytest
from sqlalchemy import func

from authz.core import Principal, Resource, permissions_for
from authz.deps import get_membership_gateway
from authz.testing import FakeMembership
from main import app
from pins.models import Pin as PinRow

MAP = "map_1"


def _insert_pin(db_session, *, map_id=MAP, created_by="user_1", kind="일반", visibility="public"):
    row = PinRow(
        id=uuid.uuid4(), map_id=map_id, category="음식점", kind=kind, origin="direct",
        place_id=f"place_{uuid.uuid4().hex[:8]}",
        geom=func.ST_SetSRID(func.ST_MakePoint(129.12, 35.15), 4326),
        visibility=visibility, created_by=created_by,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _auth(user_id="user_1"):
    return {"session": user_id}


# --- 1. API 통합 테스트 — 관측 가능한 조합만 ------------------------------------------

def test_get_pins_permissions_matches_kind_shortlist_direction(app_client, db_session):
    _insert_pin(db_session, created_by="user_1", kind="일반")
    _insert_pin(db_session, created_by="user_1", kind="확정")

    resp = app_client.get("/maps/map_1/pins", cookies=_auth("user_1"))
    assert resp.status_code == 200

    perms_by_kind = {p["kind"]: p["permissions"] for p in resp.json()}
    assert perms_by_kind["일반"]["can_add_to_shortlist"] is True
    assert perms_by_kind["일반"]["can_remove_from_shortlist"] is False
    assert perms_by_kind["확정"]["can_add_to_shortlist"] is False
    assert perms_by_kind["확정"]["can_remove_from_shortlist"] is True
    # member면 react/revert/delete는 kind와 무관하게 전부 True.
    assert perms_by_kind["일반"]["can_react"] is True
    assert perms_by_kind["일반"]["can_delete"] is True


def test_get_pins_non_member_is_404():
    """비구성원 응답 403→404 계약 변경(docs/CHANGELOG-api.md 2026-09-11) — issue #61과 같은 증거."""
    from fastapi.testclient import TestClient

    app.dependency_overrides[get_membership_gateway] = lambda: FakeMembership({})
    try:
        with TestClient(app) as client:
            resp = client.get("/maps/map_1/pins", cookies=_auth("user_1"))
    finally:
        del app.dependency_overrides[get_membership_gateway]

    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


# --- 2. 직접 단위 테스트 — 6개 조합 전부(API 응답에 안 나오는 조합 포함) ------------------

PIN_KINDS = ["일반", "AI추천", "확정"]


@pytest.mark.parametrize("kind", PIN_KINDS)
@pytest.mark.parametrize("role", ["member", None])
def test_permissions_for_pin_matches_original_matrix(kind, role):
    """원래 pins/core.py::pin_permissions(kind, is_member)가 하던 계산과 결과가 같아야 한다
    (#56 이관 안전망) — author_id를 요청자와 다르게 둬서 "남의 핀"까지 포함한다."""
    principal = Principal(user_id="user_1", map_id=MAP, role=role)
    resource = Resource(type="pin", map_id=MAP, author_id="someone_else", kind=kind)
    dumped = permissions_for(principal, resource).model_dump(exclude_none=True)

    is_member = role is not None
    assert dumped == {
        "can_react": is_member,
        "can_revert": is_member,
        "can_delete": is_member,
        "can_add_to_shortlist": is_member and kind != "확정",
        "can_remove_from_shortlist": is_member and kind == "확정",
    }
