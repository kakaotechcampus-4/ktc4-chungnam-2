"""
모듈 간 import 규칙 계약 테스트 (docs/architecture.md 1절 "모듈 간 import 규칙", 멘토 리뷰 PR #152).

규칙이 문서에만 있으면 세션이 바뀔 때마다 어긴다(recommend가 llm.service를 직접 부른 게 그 사례, #219에서 고침). 정적 검사라
DB 없이 돌고, 어긴 import를 CI가 바로 잡는다.

- 수평 레이어(common·auth·authz)는 어디서든 직접 import 가능.
- 다른 모듈은 `api`(데이터 조회·변경)와 `schemas`(응답 타입)만 import한다. `models`·`service`를 비롯한 나머지는 금지.
- 자기 모듈 안, 테스트(`tests/`·`conftest.py`·`testing.py`), `integration/`, `alembic/`, `main.py`는 검사하지 않는다
  (Alembic은 모든 모듈의 models를 읽어야 하고, main은 모든 라우터를 조립한다).

KNOWN_VIOLATIONS는 "알고 있고 이슈로 추적 중인 위반"이다. 새 위반이 생기면 실패하고, 고쳐졌는데 남아 있어도 실패한다.
"""

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
HORIZONTAL = {"common", "auth", "authz"}
ALLOWED_SUBMODULES = {"api", "schemas"}
SKIP_FILES = {"conftest.py", "testing.py", "main.py"}
SKIP_DIRS = {"tests", "integration", "alembic", "__pycache__", ".venv", "venv"}

# (importing 파일, 가져온 모듈) -> 사유. 비어 가는 것이 정상이다.
KNOWN_VIOLATIONS: dict[tuple[str, str], str] = {
}


def _modules() -> set[str]:
    return {p.name for p in BACKEND.iterdir() if p.is_dir() and (p / "__init__.py").exists()} - SKIP_DIRS


def _source_files(module: str):
    for path in (BACKEND / module).rglob("*.py"):
        rel = path.relative_to(BACKEND / module)
        if path.name in SKIP_FILES or any(part in SKIP_DIRS for part in rel.parts):
            continue
        yield path


def _imported_modules(path: Path):
    """(최상위 모듈, 두 번째 요소) 쌍. `from places import api`처럼 이름이 하위 모듈이면 그것도 두 번째 요소로 본다."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                yield parts[0], parts[1] if len(parts) > 1 else None
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            parts = node.module.split(".")
            if len(parts) > 1:
                yield parts[0], parts[1]
            else:
                for alias in node.names:
                    yield parts[0], alias.name


def _violations() -> dict[tuple[str, str], str]:
    modules = _modules()
    found: dict[tuple[str, str], str] = {}
    for module in sorted(modules):
        for path in _source_files(module):
            for top, sub in _imported_modules(path):
                if top == module or top in HORIZONTAL or top not in modules:
                    continue
                if sub in ALLOWED_SUBMODULES:
                    continue
                key = (f"{path.relative_to(BACKEND).as_posix()}", f"{top}.{sub}" if sub else top)
                found[key] = f"{module}가 {top}의 {sub or '내부'}를 직접 import"
    return found


def test_cross_module_imports_follow_the_rule():
    found = _violations()
    new = sorted(set(found) - set(KNOWN_VIOLATIONS))
    assert not new, (
        "다른 모듈의 api·schemas 밖을 import했다 — 필요한 함수를 그 모듈이 api.py에 열도록 요청한다"
        f"(docs/architecture.md 1절): {new}"
    )


def test_known_violations_are_still_violations():
    stale = sorted(set(KNOWN_VIOLATIONS) - set(_violations()))
    assert not stale, f"고쳐진 위반이 KNOWN_VIOLATIONS에 남아 있다 — 지운다: {stale}"
