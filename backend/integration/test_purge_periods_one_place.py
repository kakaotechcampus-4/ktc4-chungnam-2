"""정리 기간은 그 데이터를 가진 모듈 한 곳에서 정한다(#1474, 멘토 리뷰).

정기 정리(`maintenance/run.py`)가 `MAP_RETENTION_DAYS = 30`을 따로 두고 `maps.api.purge_deleted_maps`에 넘겼다. 정본인
`maps.core.TRASH_RETENTION`과 두 곳이 됐다. 정리 API가 기간을 인자로 받으니 부르는 쪽이 값을 다시 적을 자리가 생긴 것이다.

- 어느 모듈의 코드에도 `older_than_*` 인자가 없다 — 정리 함수는 `(db, now)`만 받고 기간은 자기 상수를 쓴다.
- `maintenance/run.py`에 기간 상수(`*_DAYS`, `*_HOURS`, `*RETENTION*`)가 없고, 설명에 「N일」「N시간」을 적지 않는다.
- maintenance 설명이 가리키는 모듈 상수(「기간을 바꿀 때는 …」)는 실제로 있다 — 가리키는 목록도 낡지 않게.

알려진 예외는 없다. 새로 걸리면 예외에 넣기 전에 루트와 정한다(CLAUDE.md 일하는 순서 5).
"""

import ast
import importlib
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MAINTENANCE = BACKEND / "maintenance" / "run.py"
SKIP_DIRS = {".venv", "alembic", "tests", "__pycache__"}
PERIOD_PARAM = re.compile(r"^older_than")
PERIOD_CONST = re.compile(r"(_DAYS|_HOURS)$|RETENTION")
PERIOD_TEXT = re.compile(r"\d+\s*(일|시간)\b")
POINTER = re.compile(r"`([a-z_]+(?:\.[a-z_]+)+)\.([A-Z][A-Z0-9_]+)`")


def _source_files():
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND)
        if not SKIP_DIRS & set(rel.parts) and rel.parts[0] != "integration":
            yield path


def period_params(tree: ast.AST) -> list[tuple[str, int, str]]:
    """함수 정의 중 기간을 인자로 받는 것: (함수, 줄, 인자)."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            for arg in args.posonlyargs + args.args + args.kwonlyargs:
                if PERIOD_PARAM.match(arg.arg):
                    found.append((node.name, node.lineno, arg.arg))
    return found


def test_no_function_takes_a_purge_period():
    found = [
        f"{path.relative_to(BACKEND).as_posix()}:{line} {name}({arg})"
        for path in _source_files()
        for name, line, arg in period_params(ast.parse(path.read_text(encoding="utf-8")))
    ]
    assert not found, (
        "정리 기간을 인자로 받는 함수가 있다 — 기간은 그 데이터를 가진 모듈의 상수로 정하고 함수는 (db, now)만 받는다(#1474):\n"
        + "\n".join(found)
    )


def test_maintenance_defines_no_period_and_does_not_restate_one():
    tree = ast.parse(MAINTENANCE.read_text(encoding="utf-8"))
    consts = [
        target.id
        for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Name) and PERIOD_CONST.search(target.id)
    ]
    assert not consts, f"maintenance/run.py에 기간 상수가 있다 — 그 데이터를 가진 모듈로 옮긴다: {consts}"
    restated = PERIOD_TEXT.findall(ast.get_docstring(tree) or "")
    assert not restated, "maintenance/run.py 설명에 기간 숫자가 있다 — 모듈 상수를 가리키기만 한다"


def test_constants_named_in_maintenance_exist():
    pointers = POINTER.findall(ast.get_docstring(ast.parse(MAINTENANCE.read_text(encoding="utf-8"))) or "")
    assert pointers, "maintenance/run.py 설명에 기간을 바꿀 자리(모듈 상수)가 없다"
    missing = [f"{module}.{name}" for module, name in pointers
               if not hasattr(importlib.import_module(module), name)]
    assert not missing, f"maintenance/run.py 설명이 가리키는 상수가 없다 — 이름이 바뀌었으면 설명을 고친다: {missing}"


def test_checks_catch_the_old_shape():
    """검사 자체: 고치기 전 maintenance의 모양(기간 인자, 기간 상수, 설명 숫자)을 잡는다."""
    old = ast.parse("def purge_deleted_maps(db, *, now, older_than_days): ...\ndef purge(db, *, now): ...")
    assert period_params(old) == [("purge_deleted_maps", 1, "older_than_days")]
    assert PERIOD_CONST.search("MAP_RETENTION_DAYS") and PERIOD_CONST.search("GUEST_INACTIVE_DAYS")
    assert not PERIOD_CONST.search("TIME_LIMIT_SECONDS") and not PERIOD_CONST.search("MAX_ROUNDS")   # 러너 자기 설정
    assert PERIOD_TEXT.findall("① 삭제한 지 30일 지난 지도 ⑦ 25시간 지난 이벤트") == ["일", "시간"]
    assert POINTER.findall("상수(`maps.core.TRASH_RETENTION`, `auth.core.GUEST_INACTIVE_DAYS`)") == [
        ("maps.core", "TRASH_RETENTION"), ("auth.core", "GUEST_INACTIVE_DAYS")]
