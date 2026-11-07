"""크레딧을 쓰는 기능의 가격·차감·환불은 명세 3.2 표 한 곳에 적고, 코드와 맞춘다(#1479, 멘토 리뷰).

환불 조건은 각 기능만 아는 사실이라 그 기능이 정한다(추천 0곳, 코스 엔진 오류). 그런데 적어 둔 곳이 서로 달랐다 —
`credits/api.py`는 코스만, 추천 CLAUDE.md와 결정표는 "추천에는 환불이 없다"(#1472). 멘토 질문: 새 기능이 크레딧을 쓰면
환불 조건은 어디에 적고 누가 확인하나? → `docs/credits-reviews.md` 3.2 「기능별 가격·차감·환불」 표에 적고, 이 검사가 코드와
맞추고, 그 PR은 루트가 검수한다.

- 표의 기능과 가격 = `credits/constants.py`의 `PRICES`
- 코드의 `credits_api.charge`·`credits_api.refund` 호출(기능, 부르는 함수) = 표의 「차감하는 곳」「환불하는 곳」
- 명세에 적힌 단가(1크레딧 = 원가 ₩N) = `CREDIT_COST_KRW`
"""

import ast
import re
from collections import defaultdict
from pathlib import Path

from credits import constants

BACKEND = Path(__file__).resolve().parents[1]
SPEC = BACKEND.parent / "docs" / "credits-reviews.md"
SECTION = "### 3.2 기능별 가격·차감·환불"
SKIP_DIRS = {".venv", "alembic", "tests", "integration", "__pycache__", "credits"}
SITE = re.compile(r"`([a-z_]+(?:\.[a-z_]+)+)`")


def read_table(markdown: str) -> dict[str, dict]:
    """3.2절 첫 표: 기능 → {price, charge: {함수}, refund: {함수}}."""
    start = markdown.index(SECTION)
    rows = {}
    for line in markdown[start:].splitlines()[1:]:
        if line.startswith("#"):
            break
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 6 or not cells[0].startswith("`"):
            if rows:
                break   # 첫 표가 끝났다(그 아래 「가격표에 없는 모델 호출」 표는 읽지 않는다)
            continue
        rows[cells[0].strip("`")] = {
            "price": int(cells[1]),
            "charge": set(SITE.findall(cells[3])),
            "refund": set(SITE.findall(cells[5])),
        }
    return rows


def _module_strings(tree: ast.Module) -> dict[str, str]:
    return {t.id: n.value.value for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
            and isinstance(n.value.value, str) for t in n.targets if isinstance(t, ast.Name)}


def credit_calls(tree: ast.Module, module: str) -> list[tuple[str, str, str]]:
    """`credits_api.charge/refund(feature=...)` 호출: (charge|refund, 기능, 부르는 함수의 점 경로)."""
    strings = _module_strings(tree)
    found = []

    def visit(node, func_name):
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else func_name
            if (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                    and child.func.attr in ("charge", "refund")
                    and isinstance(child.func.value, ast.Name) and child.func.value.id == "credits_api"):
                feature = next((k.value for k in child.keywords if k.arg == "feature"), None)
                if isinstance(feature, ast.Constant):
                    feature = feature.value
                elif isinstance(feature, ast.Name):
                    feature = strings.get(feature.id, f"<{feature.id}>")
                found.append((child.func.attr, str(feature), f"{module}.{func_name}"))
            visit(child, name)

    visit(tree, "<module>")
    return found


def code_sites() -> dict[str, dict[str, set]]:
    sites: dict[str, dict[str, set]] = defaultdict(lambda: {"charge": set(), "refund": set()})
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND)
        if SKIP_DIRS & set(rel.parts):
            continue
        module = ".".join(rel.with_suffix("").parts)
        for kind, feature, site in credit_calls(ast.parse(path.read_text(encoding="utf-8")), module):
            sites[feature][kind].add(site)
    return sites


def test_table_prices_match_price_list():
    table = read_table(SPEC.read_text(encoding="utf-8"))
    assert {f: r["price"] for f, r in table.items()} == constants.PRICES, (
        "명세 3.2 표의 기능·가격이 credits/constants.py PRICES와 다르다 — 둘을 같이 고친다(#1479)")


def test_charge_and_refund_sites_match_table():
    table = read_table(SPEC.read_text(encoding="utf-8"))
    code = code_sites()
    problems = []
    for feature in sorted(set(table) | set(code)):
        for kind, column in (("charge", "차감하는 곳"), ("refund", "환불하는 곳")):
            written = table.get(feature, {}).get(kind, set())
            actual = code.get(feature, {}).get(kind, set())
            if written != actual:
                problems.append(f"{feature} {column}: 표 {sorted(written) or '없음'} / 코드 {sorted(actual) or '없음'}")
    assert not problems, (
        "크레딧 차감·환불을 부르는 곳이 명세 3.2 표와 다르다 — 새로 부르거나 함수 이름이 바뀌면 표를 고치고, "
        "환불 조건도 그 줄에 적는다(루트 검수, #1479):\n" + "\n".join(problems))


def test_spec_states_the_credit_unit_in_code():
    stated = re.search(r"1크레딧 = 모델 원가 ₩(\d+)", SPEC.read_text(encoding="utf-8"))
    assert stated and int(stated.group(1)) == constants.CREDIT_COST_KRW, "명세 3.2의 단가와 CREDIT_COST_KRW가 다르다(#1478)"


def test_checks_catch_an_unlisted_refund():
    """검사 자체: 표에 없는 환불 호출과 상수로 넘긴 기능 이름을 읽는다."""
    tree = ast.parse('FEATURE = "course"\ndef finish(db, run_id):\n    credits_api.refund(db, feature=FEATURE, run_id=run_id)\n'
                     'def start(db):\n    credits_api.charge(db, user_id="u", feature="new_ai", run_id="r")\n')
    assert credit_calls(tree, "x.service") == [("refund", "course", "x.service.finish"), ("charge", "new_ai", "x.service.start")]
    table = read_table(f"{SECTION}\n\n| 기능 | 가격 | 원가 | 차감 | 조건 | 환불 |\n|---|---|---|---|---|---|\n"
                       "| `course` | 1 | ₩0.92 | `x.service.start` | 엔진 오류 | 없음 |\n\n| 다른 표 | x |\n")
    assert table == {"course": {"price": 1, "charge": {"x.service.start"}, "refund": set()}}
