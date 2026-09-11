"""guard.py의 require()/require_on_map()/require_map_member()가 404/403 분기를
올바르게 매기고, 허용된 경우 loader가 돌려준 obj를 그대로 통과시키는지 확인한다.

범위(DeepSeek 검수 지적 반영): 여기서 "교차 지도 시나리오에서 core.can()의 ValueError가
도달 불가능함"을 다루는 테스트(test_rule_b_mismatched_loader_rejects_before_can_is_asked)는,
이 파일 안에서 직접 만든 가짜 loader로 "loader가 Rule B를 지키면 authz는 안전하다"는
guard.py 자체의 메커니즘만 검증한다 — 실제 shortlist(#7)의 loader가 Rule B를 올바르게
구현했는지는 이 테스트가 증명하지 못한다(그 모듈이 아직 없으므로). 그건
`shortlist/mentor-review-plan.md`의 검증 항목("경로 mapId와 다른 지도의 pin_id" 테스트)이
담당한다 — 두 테스트가 각자 다른 절반을 커버한다.
"""
from dataclasses import dataclass

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from auth.deps import get_current_user
from authz.core import Resource
from authz.deps import get_membership_gateway
from authz.guard import require, require_map_member, require_on_map
from authz.service import resolve_principal
from authz.testing import FakeMembership
from common.errors import AppError, register_error_handlers


@dataclass(frozen=True)
class _CurrentUser:
    user_id: str


@dataclass(frozen=True)
class _Loaded:
    resource: Resource
    obj: object


def _client(dependency, *, path="/probe", user_id="u1", roles=None) -> TestClient:
    app = FastAPI()
    register_error_handlers(app)

    @app.get(path)
    def probe(value=Depends(dependency)):
        return {"value": value if isinstance(value, (dict, str, int, float, type(None))) else "ok"}

    app.dependency_overrides[get_current_user] = lambda: _CurrentUser(user_id=user_id)
    app.dependency_overrides[get_membership_gateway] = lambda: FakeMembership(roles or {})
    return TestClient(app)


# --- require() ---


def test_require_non_member_returns_404():
    def loader():
        return _Loaded(resource=Resource(type="pin", map_id="m1"), obj={"id": "p1"})

    client = _client(require("pin.react", loader), roles={})
    resp = client.get("/probe")
    assert resp.status_code == 404


def test_require_member_forbidden_action_returns_403():
    def loader():
        return _Loaded(resource=Resource(type="pin", map_id="m1"), obj={"id": "p1"})

    client = _client(require("map.settings.edit", loader), roles={("m1", "u1"): "member"})
    resp = client.get("/probe")
    assert resp.status_code == 403


def test_require_member_allowed_action_returns_loaded_obj():
    def loader():
        return _Loaded(resource=Resource(type="pin", map_id="m1"), obj={"id": "p1"})

    client = _client(require("pin.react", loader), roles={("m1", "u1"): "member"})
    resp = client.get("/probe")
    assert resp.status_code == 200
    assert resp.json() == {"value": {"id": "p1"}}


def test_require_loader_missing_resource_or_obj_raises_internal_error():
    class _BadLoaded:
        obj = {"id": "p1"}  # resource 없음 — hasattr 체크가 잡아야 한다

    def loader():
        return _BadLoaded()

    client = _client(require("pin.react", loader), roles={("m1", "u1"): "member"})
    resp = client.get("/probe")
    assert resp.status_code == 500


def test_rule_b_mismatched_loader_rejects_before_can_is_asked():
    """가짜 loader가 (경로 mapId, 리소스 자체 map_id)를 대조해 다르면 authz에 도달하기 전에
    NOT_FOUND를 던진다고 가정했을 때, guard.py가 loader의 예외를 그대로 통과시키는지만 본다 —
    guard.py의 배관이 loader의 판단을 존중한다는 것만 증명하고, 실제 shortlist loader가
    이렇게 구현됐는지는 증명하지 않는다(위 모듈 docstring 참고)."""

    def loader():
        raise AppError("NOT_FOUND")

    client = _client(require("pin.react", loader), roles={("m1", "u1"): "member"})
    resp = client.get("/probe")
    assert resp.status_code == 404


# --- require_on_map() ---


def test_require_on_map_non_member_returns_404():
    client = _client(require_on_map("pin.create"), path="/maps/{mapId}/probe", roles={})
    resp = client.get("/maps/m1/probe")
    assert resp.status_code == 404


def test_require_on_map_member_forbidden_action_returns_403():
    client = _client(
        require_on_map("map.settings.edit"), path="/maps/{mapId}/probe",
        roles={("m1", "u1"): "member"},
    )
    resp = client.get("/maps/m1/probe")
    assert resp.status_code == 403


def test_require_on_map_member_allowed_action_returns_200():
    client = _client(
        require_on_map("pin.create"), path="/maps/{mapId}/probe",
        roles={("m1", "u1"): "member"},
    )
    resp = client.get("/maps/m1/probe")
    assert resp.status_code == 200


# --- require_map_member() ---


def test_require_map_member_non_member_returns_404():
    client = _client(require_map_member(), path="/maps/{mapId}/probe", roles={})
    resp = client.get("/maps/m1/probe")
    assert resp.status_code == 404


def test_require_map_member_member_returns_200():
    client = _client(
        require_map_member(), path="/maps/{mapId}/probe", roles={("m1", "u1"): "member"}
    )
    resp = client.get("/maps/m1/probe")
    assert resp.status_code == 200


# --- resolve_principal: map_id는 인자를 그대로 반영한다(캐시된 값이 아니다) ---


def test_resolve_principal_map_id_reflects_argument():
    gateway = FakeMembership({("m1", "u1"): "member"})
    principal = resolve_principal(gateway, "m1", "u1")
    assert principal.map_id == "m1"
    assert principal.role == "member"
