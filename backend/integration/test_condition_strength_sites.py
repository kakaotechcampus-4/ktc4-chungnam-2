"""
조건의 세기를 정하는 곳 목록 (#731, 멘토 리뷰 #380, #680).

알러지 키 빼기(#425)는 세 번에 나눠 파일 44개, 모듈 6곳을 고쳤고, 처음 PR에서 충족 집계를 빠뜨려 열흘 뒤 다시 고쳤다(#620).
칩 원함 내리기(#617)도 같은 자리를 건드렸다. 사람이 남긴 말이 "얼마나 센 조건인가"(실격인지 선호인지)를 여러 함수가 배지(badge)
글자나 키의 hard/soft 표로 각자 판단해서다. 판단을 한 곳에 모으면(#732) 규칙이 바뀔 때 그곳만 고친다.

이 테스트는 그런 판단이 있는 함수를 찾는다.
- 배지를 "required", "preferred", "reference" 글자와 비교하는 곳
- 배지 값을 그 글자로 정해 넣는 곳(dict의 "badge" 키, badge= 인자)
- 키의 hard/soft 표(constraints.SOFT_FACT_KEYS, HARD_REGISTRY)를 읽는 곳(표를 정의하는 recommend/constraints.py는 뺀다)

지금 있는 곳은 KNOWN_SITES에 적는다. #732가 판단을 한 곳으로 모으며 비운다. 새로 생기면 실패하고(새 판단을 만들지 말고 모아 둔
함수를 부른다), 고쳐졌는데 목록에 남아 있어도 실패한다. 정적 검사라 DB 없이 돈다.

모아 둔 곳은 HOME에 적는다. 비우는 목록이 아니라 다른 곳이 불러야 하는 자리다. 없어지면 실패한다.
"""

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SKIP_DIRS = {"tests", "integration", "alembic", "__pycache__", ".venv", "venv"}
SKIP_FILES = {"recommend/constraints.py"}   # hard/soft 표의 정의 자리
BADGES = {"required", "preferred", "reference"}
STRENGTH_TABLES = {"SOFT_FACT_KEYS", "HARD_REGISTRY"}

# (파일, 함수) -> 무엇을 정하는 한 곳인가. 파이프라인, 근거 응답, agent가 이 함수를 부른다.
HOME: dict[tuple[str, str], str] = {
    ("recommend/core.py", "evidence_line_use"): "근거 줄이 이번 추천에 쓰이는지와 안 쓰이는 이유(#740)",
}

# (파일, 함수) -> 추적 이슈. 비어 가는 것이 정상이다. 2026-10-24에 처음 센 19곳.
KNOWN_SITES: dict[tuple[str, str], str] = {
    # 배지를 정해 넣는 곳(반응 종류, 칩, 「+」, 원함 내리기)
    ("recommend/flows.py", "_evidence_from_reaction"): "#732",
    ("recommend/flows.py", "_evidence_from_chip"): "#732",
    ("recommend/flows.py", "patch_evidence"): "#732",
    ("recommend/service.py", "add_manual_evidence"): "#732",
    ("recommend/core.py", "demote_wanted_place_identity"): "#732",
    ("recommend/core.py", "_demotes"): "#732",
    # 배지와 hard/soft로 실격, 점수, 확인 필요를 판단하는 곳
    ("recommend/flows.py", "_hard_fact_keys_from"): "#732",
    ("recommend/flows.py", "_soft_requirements_from"): "#732",
    ("recommend/flows.py", "_run_pipeline"): "#732",
    ("recommend/core.py", "apply_disqualifier_filters"): "#732",
    ("recommend/core.py", "_check_label"): "#732",
    ("recommend/core.py", "label_checks"): "#732",
    ("recommend/core.py", "build_preference_criteria"): "#732",
    ("recommend/core.py", "limit_preference_checks"): "#732",
    ("recommend/core.py", "checks_to_show"): "#732",
    ("recommend/core.py", "build_reason"): "#732",
    # 같은 판단을 다시 하는 곳(충족 집계, 에이전트 요약과 도구)
    ("recommend/core.py", "_member_support"): "#732",
    ("agent/core.py", "summarize_reasons"): "#732",
    ("agent/tools.py", "_lines"): "#732",
}


def _mentions_badge(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute) and node.attr == "badge":
        return True
    if isinstance(node, ast.Name) and node.id == "badge":
        return True
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and node.slice.value == "badge":
        return True
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get"
            and bool(node.args) and isinstance(node.args[0], ast.Constant) and node.args[0].value == "badge")


def _badge_constant(node: ast.AST | None) -> bool:
    """배지 글자 하나, 또는 그 글자만 고르는 조건식("required" if … else "preferred")."""
    if isinstance(node, ast.Constant):
        return node.value in BADGES
    if isinstance(node, ast.IfExp):
        return _badge_constant(node.body) or _badge_constant(node.orelse)
    return False


class _Finder(ast.NodeVisitor):
    def __init__(self):
        self.stack: list[str] = []
        self.found: set[str] = set()

    def _scope(self, node):
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _scope

    def _hit(self):
        self.found.add(".".join(self.stack) or "<module>")

    def visit_Compare(self, node):
        operands = [node.left, *node.comparators]
        if any(_badge_constant(o) for o in operands) and any(_mentions_badge(o) for o in operands):
            self._hit()
        self.generic_visit(node)

    def visit_Dict(self, node):
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and key.value == "badge" and _badge_constant(value):
                self._hit()
        self.generic_visit(node)

    def visit_keyword(self, node):
        if node.arg == "badge" and _badge_constant(node.value):
            self._hit()
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if node.attr in STRENGTH_TABLES:
            self._hit()
        self.generic_visit(node)


def _sites() -> set[tuple[str, str]]:
    found = set()
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND)
        if any(part in SKIP_DIRS for part in rel.parts) or rel.as_posix() in SKIP_FILES:
            continue
        finder = _Finder()
        finder.visit(ast.parse(path.read_text(encoding="utf-8")))
        found |= {(rel.as_posix(), func) for func in finder.found}
    return found


def test_no_new_place_decides_condition_strength():
    new = sorted(set(_sites()) - set(KNOWN_SITES) - set(HOME))
    assert not new, (
        "조건의 세기(배지, hard/soft)를 새로 판단하는 곳이 생겼다. 판단은 한 곳에 모은다(#732) — 그 함수를 부르거나, "
        f"정말 새 판단이 필요하면 루트와 정한 뒤 KNOWN_SITES에 이슈와 함께 적는다: {new}"
    )


def test_known_sites_are_still_there():
    stale = sorted(set(KNOWN_SITES) - _sites())
    assert not stale, f"한 곳으로 모아진 자리가 KNOWN_SITES에 남아 있다 — 지운다: {stale}"


def test_home_functions_still_decide():
    gone = sorted(set(HOME) - _sites())
    assert not gone, f"HOME의 함수가 없어졌거나 더는 판단하지 않는다 — 옮긴 자리로 고친다: {gone}"
