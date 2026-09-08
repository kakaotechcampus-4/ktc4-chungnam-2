"""
docs/permissions.md(정본)의 YAML 선언과 authz/policy.py::POLICY가 실제로 일치하는지, 그리고
docs/api-spec.yaml의 Permissions 스키마와 authz/schemas.py::Permissions가 일치하는지를 파싱해서
대조한다. 정본이 바뀌었는데 policy.py를 안 고치면 이 테스트가 잡는다 — authz/CLAUDE.md
"정본을 임의로 바꾸지 않는다"의 반대쪽, 즉 "정본이 바뀌면 코드도 따라와야 한다"를 지킨다.
"""

import re
from pathlib import Path

import pytest
import yaml

from authz.policy import POLICY
from authz.schemas import Permissions

DOCS_DIR = Path(__file__).resolve().parents[3] / "docs"


def _extract_first_yaml_fence(markdown_text: str) -> dict:
    match = re.search(r"```yaml\n(.*?)\n```", markdown_text, flags=re.DOTALL)
    if match is None:
        pytest.fail("docs/permissions.md에서 ```yaml 펜스를 찾지 못했습니다 — 문서 구조가 바뀌었나?")
    return yaml.safe_load(match.group(1))


@pytest.fixture(scope="module")
def declared_policy() -> dict:
    text = (DOCS_DIR / "permissions.md").read_text(encoding="utf-8")
    return _extract_first_yaml_fence(text)


def test_role_names_match(declared_policy):
    assert set(declared_policy.keys()) == set(POLICY.keys())


@pytest.mark.parametrize("role", ["member", "author", "owner"])
def test_role_scope_matches(declared_policy, role):
    assert declared_policy[role]["scope"] == dict(POLICY[role].scope)


@pytest.mark.parametrize("role", ["member", "author", "owner"])
def test_role_actions_match(declared_policy, role):
    assert set(declared_policy[role]["actions"]) == set(POLICY[role].actions)


def test_permissions_schema_fields_match_api_spec():
    spec_text = (DOCS_DIR / "api-spec.yaml").read_text(encoding="utf-8")
    spec = yaml.safe_load(spec_text)
    spec_fields = set(spec["components"]["schemas"]["Permissions"]["properties"].keys())
    model_fields = set(Permissions.model_fields.keys())
    assert spec_fields == model_fields
