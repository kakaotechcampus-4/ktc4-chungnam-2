"""② 규칙 버전(#1095) — 같은 프롬프트와 스키마면 같은 값, 12자 16진, 프롬프트가 바뀌면 달라진다. 모델을 부르지 않는다."""

import re

from llm import api


def test_version_is_12_hex_and_stable():
    v = api.plan_evidence_rules_version()
    assert re.fullmatch(r"[0-9a-f]{12}", v)
    assert api.plan_evidence_rules_version() == v


def test_version_changes_when_the_prompt_changes(monkeypatch):
    before = api.plan_evidence_rules_version()
    monkeypatch.setattr(api, "PLAN_EVIDENCE_PROMPT", api.PLAN_EVIDENCE_PROMPT + "\n9. 새 규칙")
    assert api.plan_evidence_rules_version() != before
