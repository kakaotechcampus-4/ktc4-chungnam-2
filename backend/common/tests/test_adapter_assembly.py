"""common/adapters.py 테스트 — 포트 조립 레지스트리와 prod 가드."""

import ast
from pathlib import Path

import pytest

# 실구현이 아직 없는 포트 목록. 새 포트를 추가했는데 여기 안 적으면 테스트가 실패한다.
# 주의: "pins.EventPublisher"는 여기 없다 — 이벤트 발행은 select()로 고르는 포트가 아니라
# common.events.record_event를 직접 부르는 평범한 함수 호출로 바뀐다(pins 계획 참고).
# 구현이 영원히 하나뿐인 것에 어댑터 선택 레이어를 씌우지 않는다.
MISSING_REAL = {
    "pins.PlaceGateway": "#34",
    "authz.MembershipGateway": "#19",
    "auth.SessionResolver": "#4",
}


@pytest.mark.xfail(strict=False, reason="pins/authz/auth의 deps.py가 아직 select()로 재배선되지 않았다")
def test_every_registered_port_is_accounted_for():
    """이 테스트는 pins/authz/auth가 select()로 재배선을 마친 뒤에만 통과한다 —
    그 전까지는 xfail(strict=False)로 표시해두고, 각 모듈의 계획 완료 후 strict로 바꾼다."""
    import main  # noqa: F401 — 모든 deps.py를 import시켜 레지스트리를 채운다
    from common.adapters import assembly
    ports = {c.port for c in assembly()}
    assert ports == set(MISSING_REAL), "포트를 추가/삭제했으면 MISSING_REAL도 같이 고친다"


def test_prod_refuses_to_boot_while_real_impls_are_missing():
    """이건 pins/authz와 무관하게 지금 당장 strict로 통과해야 한다 — Settings를 직접
    생성해서 __post_init__ 가드만 검사하므로 select() 재배선을 기다릴 이유가 없다.
    (DeepSeek 검수 지적: 원래 이 두 테스트를 같이 xfail로 묶으려 했으나, 이 테스트는
    select()에 의존하지 않으므로 분리해서 지금 바로 strict 통과시킨다.)"""
    from common.settings import ConfigError, Settings
    with pytest.raises(ConfigError, match="prod"):
        Settings(environment="prod", database_url="x", cors_allow_origins=(),
                 cors_allow_origin_regex=None, session_secret="s",
                 places_mode="dev", membership_mode="real", auth_mode="real")


def test_select_registers_the_choice_in_assembly():
    """select()/assembly()의 핵심 동작 자체 — 2차 DeepSeek 재검수가 이 레지스트리 코어
    로직을 직접 검사하는 테스트가 없다고 지적. dev/real 여부와 무관하게 지금 바로 돈다.

    주의: _REGISTRY는 모듈 전역이라 "test.FakePort"를 남겨두면 다른 테스트(특히
    test_every_registered_port_is_accounted_for의 set 비교)를 오염시킨다 — 반드시 finally에서
    지운다."""
    import common.adapters as adapters_module
    from common.adapters import assembly, select

    try:
        factory = select("test.FakePort", "dev", {"dev": lambda: "fake", "real": None})
        assert factory() == "fake"
        choice = next(c for c in assembly() if c.port == "test.FakePort")
        assert choice.mode == "dev"
    finally:
        adapters_module._REGISTRY.pop("test.FakePort", None)


# 새 dev/real 어댑터 포트가 생기면 여기 추가한다 — 위 settings.py의 _PORTS,
# adapters.py의 select() 호출 이름들과 맞춘다. pins·authz가 각각 select()로 재배선을
# 마쳤으므로 여기 등록한다.
KNOWN_ADAPTER_FACTORIES = {"get_place_gateway", "get_membership_gateway"}


def _select_bound_names(tree: ast.Module) -> set[str]:
    """`X = select(...)` 형태의 대입 좌변 이름들."""
    names = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "select"):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def test_adapter_factories_go_through_select():
    """dev/real 두 구현을 오갈 수 있는 어댑터 팩토리(KNOWN_ADAPTER_FACTORIES)는 반드시
    select()의 반환값이어야 한다. 직접 `def get_place_gateway(): return RequestEchoPlaceGateway()`
    처럼 정의하면 select()를 완전히 우회해 prod 가드가 무의미해진다 — 이 패턴만 정확히 잡는다.
    get_current_user도 auth(#4) 전까지는 dev 스텁과 실구현을 오가야 하므로 이제 이 목록에 있다
    (auth/mentor-review-plan.md 후속) — get_db_session·리소스 로더처럼 애초에 dev/real 구분이
    없는 Depends 대상만 이 테스트의 관심사 밖이다(그런 것까지 오탐했던 이전 버전의 문제를
    여기서 바로잡음)."""
    for path in Path(__file__).resolve().parents[2].glob("*/deps.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        select_bound = _select_bound_names(tree)
        directly_defined = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        bypassed = (KNOWN_ADAPTER_FACTORIES & directly_defined) - select_bound
        assert not bypassed, f"{path}: {bypassed}가 select() 없이 def로 직접 정의됐다"
