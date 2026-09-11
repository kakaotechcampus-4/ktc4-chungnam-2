"""Rule A('resolve_principal은 authz.guard에서만 부른다')는 강제 코드가 아니라 관례다
(DeepSeek 검수 지적). 최소한 정적으로라도 깨졌는지 알 수 있게 해둔다."""
import ast
from pathlib import Path


def test_only_guard_module_calls_resolve_principal():
    root = Path(__file__).resolve().parents[2]   # backend/
    violations = []
    for path in root.glob("*/*.py"):
        if path.name in {"guard.py", "service.py"} or "tests" in path.parts:
            continue   # authz/guard.py 자신, authz/service.py(정의부) 제외
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "resolve_principal"):
                violations.append(str(path))
    assert not violations, f"resolve_principal을 authz.guard 밖에서 직접 호출: {violations}"
