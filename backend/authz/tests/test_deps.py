"""issue #89 회귀 방지 — membership에 dev/real 두 구현이 있어 잘못 고를 수 있던 상태로
되돌아가지 않는지 못박는다. `AllowAllMembership`(늘 'member') 스텁을 완전히 제거하고
`get_membership_gateway`를 `maps.api.DbMembershipGateway` 하나로 단순화했다(authz/deps.py).
"""

import ast
from pathlib import Path

import authz.deps
from authz.deps import get_membership_gateway
from maps.api import DbMembershipGateway


def test_get_membership_gateway_always_resolves_to_db_membership_gateway():
    """모드 분기 없이 항상 DbMembershipGateway를 돌려준다 — db 인자를 그대로 들고 있을
    뿐이라(DbMembershipGateway.__init__), 진짜 DB 세션이 없어도 이 사실만은 확인할 수 있다."""
    fake_db = object()
    gateway = get_membership_gateway(fake_db)
    assert isinstance(gateway, DbMembershipGateway)
    assert gateway._db is fake_db


def test_allow_all_membership_stub_is_gone():
    """이름 자체가 authz.deps 네임스페이스에서 사라졌는지."""
    assert not hasattr(authz.deps, "AllowAllMembership")
    assert not hasattr(authz.deps, "_dev_membership")
    assert not hasattr(authz.deps, "_real_membership")


def test_no_unconditional_member_stub_remains_in_authz_deps_source():
    """이름을 바꿔서 스텁을 되살리는 것까지 잡는다 — authz/deps.py 안에 인자와 무관하게
    무조건 문자열 리터럴 "member"를 반환하는 get_role이 있으면(=예전 AllowAllMembership과
    같은 모양) 실패한다. AST로 소스 자체를 본다(authz/tests/test_rule_a_static.py와 같은 방식)."""
    source = Path(authz.deps.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=authz.deps.__file__)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "get_role":
            for stmt in ast.walk(node):
                if (
                    isinstance(stmt, ast.Return)
                    and isinstance(stmt.value, ast.Constant)
                    and stmt.value.value == "member"
                ):
                    raise AssertionError(
                        "authz/deps.py에 무조건 'member'를 반환하는 get_role이 남아있다 — "
                        "AllowAllMembership류 스텁이 되살아난 것으로 보인다"
                    )
