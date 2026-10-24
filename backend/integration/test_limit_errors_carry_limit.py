"""
상한 오류는 상한 값을 실어 보낸다 (#733, 멘토 리뷰 #380, #680 회고 #731).

지도 상한을 10에서 20으로 바꿨을 때(#433) 화면에는 "10개까지"가 숫자로 남아 있었고, 목록 응답에 상한을 함께 내리고 나서야(#623)
한 곳만 고치면 되게 됐다. 정책 값이 화면에 숫자로 박혀 있으면 값을 바꿀 때마다 화면을 찾아다녀야 한다.

이 테스트는 이름이 `_LIMIT`으로 끝나는 오류를 일으키는 곳(AppError("…_LIMIT", detail=…))이 detail에 상한 값(이름에 limit이
들어간 키)을 싣는지 본다. 화면은 그 값으로 문구를 만들고 숫자를 적지 않는다(루트 CLAUDE.md "일하는 순서").
"""

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SKIP_DIRS = {"tests", "integration", "alembic", "__pycache__", ".venv", "venv"}

# (파일, 코드) -> 추적 이슈. 비어 가는 것이 정상이다.
KNOWN_WITHOUT_LIMIT: dict[tuple[str, str], str] = {
    ("auth/service.py", "GUEST_LIMIT"): "#733",
    ("recommend/core.py", "WIDEN_LIMIT"): "#733",
}


def _carries_limit(call: ast.Call) -> bool:
    detail = next((kw.value for kw in call.keywords if kw.arg == "detail"), None)
    return isinstance(detail, ast.Dict) and any(
        isinstance(key, ast.Constant) and isinstance(key.value, str) and "limit" in key.value for key in detail.keys
    )


def _limit_raises() -> dict[tuple[str, str], bool]:
    found: dict[tuple[str, str], bool] = {}
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == "AppError"
                    and node.args and isinstance(node.args[0], ast.Constant)
                    and str(node.args[0].value).endswith("_LIMIT")):
                key = (rel.as_posix(), node.args[0].value)
                found[key] = found.get(key, True) and _carries_limit(node)
    return found


def test_limit_errors_carry_the_limit():
    missing = sorted(k for k, ok in _limit_raises().items() if not ok and k not in KNOWN_WITHOUT_LIMIT)
    assert not missing, (
        "상한 오류인데 detail에 상한 값이 없다 — 화면이 숫자를 적게 된다. detail에 { limit, … }을 싣는다(errors.md 함께): "
        f"{missing}"
    )


def test_known_entries_still_lack_the_limit():
    raises = _limit_raises()
    stale = sorted(k for k in KNOWN_WITHOUT_LIMIT if raises.get(k, True))
    assert not stale, f"이제 상한 값을 싣거나 없어진 자리가 KNOWN_WITHOUT_LIMIT에 남아 있다 — 지운다: {stale}"
