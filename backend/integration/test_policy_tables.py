"""
정책 표는 문서가 정본이고, 테스트는 표의 모든 행을 읽는다 (#731, 멘토 리뷰 #680).

칩 배지(#617)는 문서 문단과 recommend.core의 예외 목록에만 있었고, 테스트는 「휠체어·유모차」 칩 id를 직접 적었다. ♥ 표(#414,
#681-3)는 키 40여 개를 테스트에 한 번 더 적어 문서, 코드, 테스트 세 벌이 됐다. 값을 바꿀 때 세 곳을 고쳐야 하고, 테스트만
고치면 문서와 코드가 달라도 통과한다.

이 테스트는 docs/constraints.md의 표를 읽어 행마다 실제 동작과 비교한다. id와 키는 여기 적지 않는다.
- 「반대 사유 칩 (v1)」 표의 배지 열: 칩 → 근거 줄(recommend.flows) → 원함 내리기(recommend.api)를 거친 배지
- 「♥에서 선호로 쓰는 라벨」 두 표: recommend.constraints.heart_signal_use의 결과, 양방향
칩 표의 나머지 열(id, label, 카테고리, fact_key, wants)은 pins/tests/test_chips.py가 본다.
"""

import re
from pathlib import Path

import pytest

from pins import chips
from recommend import api as recommend_api
from recommend import constraints
from recommend.flows import _evidence_from_chip

CONSTRAINTS = (Path(__file__).resolve().parents[2] / "docs" / "constraints.md").read_text(encoding="utf-8")
NONE = "(없음)"
USE = {"쓴다": "use", "2곳 이상": "two_or_more", "쓰지 않음": "unused"}


def _section(title: str) -> str:
    """제목이 title로 시작하는 절의 본문(다음 같은 단계 이상 제목 전까지)."""
    match = re.search(rf"^(#+) {re.escape(title)}.*$", CONSTRAINTS, re.MULTILINE)
    assert match, f"docs/constraints.md에서 「{title}」 절을 못 찾았다 — 제목이 바뀌었나?"
    level = len(match.group(1))
    rest = CONSTRAINTS[match.end():]
    end = re.search(rf"^#{{1,{level}}} ", rest, re.MULTILINE)
    return rest[: end.start() if end else len(rest)]


def _rows(section: str) -> list[list[str]]:
    """표의 데이터 행(머리줄과 구분줄 제외)을 칸 목록으로."""
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in section.splitlines() if line.strip().startswith("|")
    ]
    return [row for row in rows[2:] if not set("".join(row)) <= set("-: ")]


# ---------- 반대 사유 칩: 배지 열 ----------

def _chip_rows() -> list[dict]:
    rows = [
        dict(zip(("id", "label", "category", "fact_key", "wants", "badge"), row))
        for row in _rows(_section("반대 사유 칩 (v1)")) if len(row) == 6
    ]
    assert rows, "칩 표를 못 읽었다"
    return rows


def _badge_after_assembly(chip_id: str, category: str) -> str | None:
    """서버가 칩 반응에서 근거 줄을 만들고 원함을 내린 뒤의 배지. 키가 없는 칩은 효과가 없으므로 None."""
    [chip] = chips.evidence_chips([chip_id])
    line = _evidence_from_chip({"user_id": "u"}, chip)
    [line] = recommend_api.demote_wanted_place_identity(category, [line])
    return line["badge"] if line["fact_key"] else None


def test_chip_badge_column_only_uses_known_values():
    bad = sorted((r["id"], r["badge"]) for r in _chip_rows() if r["badge"] not in ("required", "preferred", NONE))
    assert not bad, f"칩 표의 배지 열에는 required, preferred, {NONE}만 쓴다: {bad}"


@pytest.mark.parametrize("row", _chip_rows(), ids=lambda r: r["id"])
def test_chip_badge_column_matches_what_recommend_assembles(row):
    want = None if row["badge"] == NONE else row["badge"]
    got = _badge_after_assembly(row["id"], row["category"])
    assert got == want, (
        f"{row['id']}({row['label']}): 문서 배지 {row['badge']} / 근거 조립 결과 {got or NONE}. 문서 표가 정본이다 — "
        "값을 바꾸려면 표와 recommend.core.REQUIRED_WANTED_CHIP_IDS를 같이 고친다"
    )


# ---------- ♥에서 선호로 쓰는 라벨 ----------

def _use_of(cell: str) -> str:
    use = next((value for word, value in USE.items() if cell.startswith(word)), None)
    assert use, f"♥ 표의 「♥ 핀에서」 칸을 모르는 값으로 썼다: {cell!r} — {list(USE)} 중 하나로 시작해야 한다"
    return use


def _keys_in(cell: str, category: str) -> set[str]:
    """칸 안의 `키`들. `cuisine_*` N개처럼 접두사로 쓴 칸은 등록된 soft 키로 펼치고 개수를 맞춘다."""
    keys = set()
    for token in re.findall(r"`([a-z_*]+)`", cell):
        if token.endswith("*"):
            expanded = {k for k in constraints.soft_fact_keys_for(category) if k.startswith(token[:-1])}
            count = re.search(rf"`{re.escape(token)}` (\d+)개", cell)
            assert count and int(count.group(1)) == len(expanded), (
                f"♥ 표의 `{token}` 개수({count and count.group(1)})와 등록된 키 수({len(expanded)})가 다르다"
            )
            keys |= expanded
        else:
            keys.add(token)
    return keys


def _heart_tables() -> dict[str, dict[str, str]]:
    """카테고리 → 키 → 쓰는 법. 표의 머리줄에서 카테고리 열을 읽는다."""
    table: dict[str, dict[str, str]] = {}
    for title in ("♥에서 선호로 쓰는 라벨 (음식점)", "♥에서 선호로 쓰는 라벨 (카페·관광지)"):
        section = _section(title)
        header = [cell.strip() for cell in next(
            line for line in section.splitlines() if line.strip().startswith("|")
        ).strip().strip("|").split("|")]
        categories = header[2:] if header[2:] != ["키"] else [title.split("(")[1].rstrip(")")]
        for row in _rows(section):
            use = _use_of(row[1])
            for category, cell in zip(categories, row[2:]):
                for key in _keys_in(cell, category):
                    assert key not in table.setdefault(category, {}), f"♥ 표에 {category} {key}가 두 번 있다"
                    table[category][key] = use
    assert table, "♥ 표를 못 읽었다"
    return table


def test_heart_tables_match_heart_signal_use():
    wrong = sorted(
        f"{category} {key}: 문서 {use} / 코드 {constraints.heart_signal_use(category, key)}"
        for category, keys in _heart_tables().items() for key, use in keys.items()
        if constraints.heart_signal_use(category, key) != use
    )
    assert not wrong, f"♥ 표와 recommend.constraints.HEART_SIGNAL_BY_CATEGORY가 다르다:\n- " + "\n- ".join(wrong)


def test_heart_signal_code_has_nothing_the_tables_lack():
    doc = _heart_tables()
    extra = sorted(
        f"{category} {key}" for category, keys in constraints.HEART_SIGNAL_BY_CATEGORY.items()
        for key in keys if key not in doc.get(category, {})
    )
    assert not extra, f"코드에만 있는 ♥ 표 키 — 문서 표에 먼저 넣는다: {extra}"


def test_heart_tables_only_use_registered_soft_keys():
    unknown = sorted(
        f"{category} {key}" for category, keys in _heart_tables().items()
        for key in set(keys) - set(constraints.soft_fact_keys_for(category))
    )
    assert not unknown, f"♥ 표에 그 카테고리 soft 키가 아닌 것이 있다: {unknown}"


def test_restaurant_heart_table_covers_every_restaurant_soft_key():
    """문서: "새 음식점 soft 키를 등록하면 이 표에도 넣는다"(#414)."""
    missing = sorted(set(constraints.soft_fact_keys_for("음식점")) - set(_heart_tables()["음식점"]))
    assert not missing, f"음식점 soft 키인데 ♥ 표(음식점)에 없다: {missing}"


def test_two_or_more_threshold_matches_the_table_wording():
    words = {
        int(n)
        for title in ("♥에서 선호로 쓰는 라벨 (음식점)", "♥에서 선호로 쓰는 라벨 (카페·관광지)")
        for row in _rows(_section(title)) for n in re.findall(r"(\d+)곳 이상", row[1])
    }
    assert words == {constraints.HEART_SIGNAL_MIN_TRUE_PLACES}, (
        f"표의 'N곳 이상'({sorted(words)})과 HEART_SIGNAL_MIN_TRUE_PLACES({constraints.HEART_SIGNAL_MIN_TRUE_PLACES})가 다르다"
    )
