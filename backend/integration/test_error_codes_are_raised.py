"""
스펙의 오류 코드는 코드에서 실제로 쓰인다 (#733, 멘토 리뷰 #680 회고 #731).

「+」 직접 추가(#707)는 상한과 `EVIDENCE_LIMIT`을 문서, 목 서버, 오류 목록(common/errors.py)에 먼저 넣고 구현은 따로 했다. 그 사이
QA가 "스펙에는 있는데 서버는 막지 않는다"를 찾았고(#716), 같은 상한이 두 사람에게서 두 번 구현됐다. 계약만 바뀌고 구현이 없는
상태가 조용히 지나가지 않게 한다.

errors.md와 CATALOG가 같은지는 common/tests/test_errors.py가 본다. 이 테스트는 CATALOG의 오류 코드(200이 아닌 것)가 backend 코드
어딘가에서 글자로 쓰이는지 본다(AppError("CODE") 등). 아직 구현이 없는 코드는 KNOWN_UNRAISED에 이슈와 함께 적는다.
"""

import ast
from pathlib import Path

from common.errors import CATALOG

BACKEND = Path(__file__).resolve().parents[1]
SKIP_DIRS = {"tests", "integration", "alembic", "__pycache__", ".venv", "venv"}
SKIP_FILES = {"common/errors.py"}   # 목록을 정의하는 자리

# 코드 -> 추적 이슈. 비어 가는 것이 정상이다.
KNOWN_UNRAISED: dict[str, str] = {
    "IDEMPOTENCY_CONFLICT": "#48의 첫 적용처는 POST /maps/{mapId}/runs로 정했다 — 서버 구현 전(#811 2/3). 구현되면 지운다",
    "REQUEST_IN_PROGRESS": "같은 Idempotency-Key의 첫 요청 처리 중 — 서버 구현 전(#811 2/3). 구현되면 지운다",
    "NO_PENDING_LOGIN": "탈퇴 계정 재로그인 선택(GET·POST /auth/pending) — 서버 구현 전(#857). 구현되면 지운다",
}


def _used_codes() -> set[str]:
    used = set()
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND)
        if any(part in SKIP_DIRS for part in rel.parts) or rel.as_posix() in SKIP_FILES:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in CATALOG:
                used.add(node.value)
    return used


def _raisable() -> set[str]:
    return {code for code, (status, _) in CATALOG.items() if status != 200}


def test_every_raisable_error_code_is_used():
    unused = sorted(_raisable() - _used_codes() - set(KNOWN_UNRAISED))
    assert not unused, (
        "오류 목록(errors.md, CATALOG)에 있는데 코드에서 쓰지 않는 코드 — 계약만 바뀌고 구현이 없다. 구현하거나, 구현 이슈와 함께 "
        f"KNOWN_UNRAISED에 적는다: {unused}"
    )


def test_known_unraised_codes_are_still_unused():
    stale = sorted(set(KNOWN_UNRAISED) & _used_codes())
    assert not stale, f"이제 쓰이는 코드가 KNOWN_UNRAISED에 남아 있다 — 지운다: {stale}"
