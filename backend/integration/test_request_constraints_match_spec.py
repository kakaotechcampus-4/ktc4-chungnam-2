"""
요청 본문 제약은 스펙과 서버가 같다 (#733, 멘토 리뷰 #680 회고 #731).

「+」 직접 추가(#707)는 스펙에 `add` maxItems 5를 적었지만 서버 요청 모델에는 상한이 없어 6줄이 200으로 들어갔다(QA #716).
응답 모양은 test_response_contract.py가 보지만 요청 쪽 제약은 아무도 대조하지 않았다.

이 테스트는 docs/api-spec.yaml의 요청 본문(POST, PUT, PATCH의 application/json)과 서버가 만든 OpenAPI(app.openapi(), pydantic
요청 모델)의 maxItems, minItems, maxLength, minLength, maximum, minimum을 필드마다 비교한다. 다르면 서버가 실제로 막는 것과 화면이
믿는 것이 다르다는 뜻이다. 처음 돌릴 때 찾은 불일치는 KNOWN_DRIFT에 적고 #733이 비운다.
"""

import re
from pathlib import Path

import yaml

from main import app

SPEC = yaml.safe_load((Path(__file__).resolve().parents[2] / "docs" / "api-spec.yaml").read_text(encoding="utf-8"))
KEYS = ("maxItems", "minItems", "maxLength", "minLength", "maximum", "minimum")

# (메서드, 경로, 필드.제약) -> 추적 이슈. 비어 가는 것이 정상이다.
KNOWN_DRIFT: dict[tuple[str, str, str], str] = {
    ("PATCH", "/maps/{mapId}", ".region.lat.maximum"): "#733",   # 스펙 90 / 서버 None
    ("PATCH", "/maps/{mapId}", ".region.lat.minimum"): "#733",   # 스펙 -90 / 서버 None
    ("PATCH", "/maps/{mapId}", ".region.lng.maximum"): "#733",   # 스펙 180 / 서버 None
    ("PATCH", "/maps/{mapId}", ".region.lng.minimum"): "#733",   # 스펙 -180 / 서버 None
    ("PATCH", "/maps/{mapId}", ".title.minLength"): "#733",   # 스펙 1 / 서버 None
    ("POST", "/feedback", ".message.maxLength"): "#733",   # 스펙 1000 / 서버 None
    ("POST", "/feedback", ".message.minLength"): "#733",   # 스펙 1 / 서버 None
    ("POST", "/maps", ".region.lat.maximum"): "#733",   # 스펙 90 / 서버 None
    ("POST", "/maps", ".region.lat.minimum"): "#733",   # 스펙 -90 / 서버 None
    ("POST", "/maps", ".region.lng.maximum"): "#733",   # 스펙 180 / 서버 None
    ("POST", "/maps", ".region.lng.minimum"): "#733",   # 스펙 -180 / 서버 None
    ("POST", "/maps/{mapId}/pins", ".link_url.maxLength"): "#733",   # 스펙 2000 / 서버 None
    ("POST", "/maps/{mapId}/pins/bulk", ".pins[].address.maxLength"): "#733",   # 스펙 200 / 서버 None
    ("POST", "/maps/{mapId}/pins/bulk", ".pins[].kakao_place_id.maxLength"): "#733",   # 스펙 100 / 서버 None
    ("POST", "/maps/{mapId}/pins/bulk", ".pins[].kakao_place_id.minLength"): "#733",   # 스펙 1 / 서버 None
    ("POST", "/maps/{mapId}/pins/bulk", ".pins[].lat.maximum"): "#733",   # 스펙 90 / 서버 None
    ("POST", "/maps/{mapId}/pins/bulk", ".pins[].lat.minimum"): "#733",   # 스펙 -90 / 서버 None
    ("POST", "/maps/{mapId}/pins/bulk", ".pins[].link_url.maxLength"): "#733",   # 스펙 2000 / 서버 None
    ("POST", "/maps/{mapId}/pins/bulk", ".pins[].lng.maximum"): "#733",   # 스펙 180 / 서버 None
    ("POST", "/maps/{mapId}/pins/bulk", ".pins[].lng.minimum"): "#733",   # 스펙 -180 / 서버 None
    ("POST", "/maps/{mapId}/pins/bulk", ".pins[].memo.maxLength"): "#733",   # 스펙 200 / 서버 None
    ("POST", "/maps/{mapId}/pins/bulk", ".pins[].place_id.maxLength"): "#733",   # 스펙 100 / 서버 None
    ("POST", "/maps/{mapId}/pins/bulk", ".pins[].place_name.maxLength"): "#733",   # 스펙 100 / 서버 None
    ("POST", "/maps/{mapId}/pins/bulk", ".pins[].search_query.maxLength"): "#733",   # 스펙 100 / 서버 None
    ("POST", "/maps/{mapId}/pins/bulk", ".pins[].search_query.minLength"): "#733",   # 스펙 1 / 서버 None
}


def _resolve(doc: dict, node):
    while isinstance(node, dict) and "$ref" in node:
        target = doc
        for part in node["$ref"].split("#/")[-1].split("/"):
            target = target[part]
        node = target
    return node


def _constraints(doc: dict, schema, prefix: str = "") -> dict[str, object]:
    """필드 경로(.add[].text) → 제약 값. null 갈래(anyOf의 type null)는 건너뛴다."""
    schema = _resolve(doc, schema)
    if not isinstance(schema, dict):
        return {}
    out = {f"{prefix}.{key}": schema[key] for key in KEYS if key in schema}
    for name, sub in (schema.get("properties") or {}).items():
        out |= _constraints(doc, sub, f"{prefix}.{name}")
    if "items" in schema:
        out |= _constraints(doc, schema["items"], f"{prefix}[]")
    for branch in ("anyOf", "oneOf", "allOf"):
        for sub in schema.get(branch) or []:
            if _resolve(doc, sub).get("type") != "null":
                out |= _constraints(doc, sub, prefix)
    return out


def _request_schema(doc: dict, op: dict):
    return ((op.get("requestBody") or {}).get("content") or {}).get("application/json", {}).get("schema")


def _drift() -> dict[tuple[str, str, str], tuple[object, object]]:
    generated = app.openapi()
    norm = lambda p: re.sub(r"\{[^}]+\}", "{}", p)   # noqa: E731
    served = {norm(path): ops for path, ops in generated["paths"].items()}
    found = {}
    for path, ops in SPEC["paths"].items():
        for method, op in ops.items():
            if method not in ("post", "put", "patch"):
                continue
            spec_schema = _request_schema(SPEC, op)
            app_schema = _request_schema(generated, (served.get(norm(path)) or {}).get(method) or {})
            if not spec_schema or not app_schema:
                continue
            want, have = _constraints(SPEC, spec_schema), _constraints(generated, app_schema)
            for field in set(want) | set(have):
                if want.get(field) != have.get(field):
                    found[(method.upper(), path, field)] = (want.get(field), have.get(field))
    return found


def test_request_constraints_match_the_spec():
    drift = _drift()
    new = sorted(f"{m} {p} {f}: 스펙 {drift[(m, p, f)][0]} / 서버 {drift[(m, p, f)][1]}"
                 for (m, p, f) in drift if (m, p, f) not in KNOWN_DRIFT)
    assert not new, (
        "요청 본문 제약이 스펙(docs/api-spec.yaml)과 서버 요청 모델이 다르다 — 화면이 믿는 것과 서버가 막는 것이 다르다. 둘을 "
        "같이 고친다:\n- " + "\n- ".join(new)
    )


def test_known_drift_is_still_there():
    stale = sorted(set(KNOWN_DRIFT) - set(_drift()))
    assert not stale, f"맞춰진 제약이 KNOWN_DRIFT에 남아 있다 — 지운다: {stale}"
