"""탈퇴한 사람의 표시 이름은 auth 한 곳에서 정한다(#1475).

「탈퇴한 구성원」이 auth(`core.WITHDRAWN_DISPLAY_NAME`), maps, pins, notifications 네 곳에 따로 적혀 있었다. pins는 복사본이
정본과 같은지 대조하는 테스트까지 두었다. 문구를 바꾸면 한쪽만 바뀐다(멘토 리뷰에서 같은 값을 두 곳에 둔 곳을 찾다가 나왔다, #1474).
다른 모듈은 `auth.api.WITHDRAWN_DISPLAY_NAME`을 import하고, 그 글자를 문자열로 다시 적지 않는다.
"""

import ast
from pathlib import Path

from auth.api import WITHDRAWN_DISPLAY_NAME

BACKEND = Path(__file__).resolve().parents[1]
OWNER = Path("auth") / "core.py"
SKIP_DIRS = {".venv", "alembic", "tests", "integration", "__pycache__"}


def string_literals(tree: ast.AST, value: str) -> list[int]:
    """설명(docstring)이 아닌 코드 안에서 정확히 그 글자인 문자열 상수의 줄."""
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)
    }
    return [node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and node.value == value and id(node) not in docstrings]


def test_withdrawn_display_name_is_written_only_in_auth():
    found = []
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND)
        if SKIP_DIRS & set(rel.parts) or rel == OWNER:
            continue
        found += [f"{rel.as_posix()}:{line}" for line in string_literals(ast.parse(path.read_text(encoding="utf-8")), WITHDRAWN_DISPLAY_NAME)]
    assert not found, (
        f"「{WITHDRAWN_DISPLAY_NAME}」을 auth 밖에서 다시 적었다 — auth.api.WITHDRAWN_DISPLAY_NAME을 import한다(#1475):\n" + "\n".join(found)
    )


def test_check_catches_a_copy_but_not_a_docstring():
    copy = ast.parse('"""탈퇴한 구성원을 내려준다."""\nNAME = "탈퇴한 구성원"\n')
    assert string_literals(copy, "탈퇴한 구성원") == [2]
