"""llm 사유 구조화 fact_key ↔ docs/constraints.md 계약 테스트 (#215).

constraints.md 조건 표의 fact_key와 llm.schemas.FactKey가 양방향으로 같아야 한다.
문서에만 키를 넣으면 ②가 그 키를 내지 못해 사람 말이 조용히 버려지고(fact_key=null),
코드에만 넣으면 recommend 레지스트리가 모르는 키가 된다 — 어느 쪽이든 여기서 실패한다.

is_open·within_radius는 문서에서도 "코드 판정"이라 사유 구조화 대상이 아니다.
"""

import re
from pathlib import Path
from typing import get_args

from llm.prompts import FACT_KEY_MEANINGS
from llm.schemas import FactKey

CONSTRAINTS_MD = Path(__file__).resolve().parents[2] / "docs" / "constraints.md"
CODE_JUDGED = frozenset({"is_open", "within_radius"})


def _doc_fact_keys() -> set[str]:
    """조건 표 행(첫 칸이 `key`로 시작하는 줄)에서 fact_key를 뽑는다. 표 머리(`fact_key`)는 뺀다."""
    keys: set[str] = set()
    for line in CONSTRAINTS_MD.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*`([a-z_]+)`", line)
        if m and m.group(1) != "fact_key":
            keys.add(m.group(1))
    return keys - CODE_JUDGED


def test_doc_and_fact_key_are_the_same_set():
    doc, code = _doc_fact_keys(), set(get_args(FactKey))
    assert doc, "constraints.md에서 fact_key를 하나도 못 읽었다 — 표 형식이 바뀌었나"
    assert not doc - code, f"문서에만 있는 fact_key(llm/schemas.py FactKey와 prompts.FACT_KEY_MEANINGS에 추가): {sorted(doc - code)}"
    assert not code - doc, f"코드에만 있는 fact_key(루트가 문서에 먼저 등록해야 한다): {sorted(code - doc)}"


def test_every_fact_key_has_a_prompt_meaning():
    assert set(FACT_KEY_MEANINGS) == set(get_args(FactKey))
