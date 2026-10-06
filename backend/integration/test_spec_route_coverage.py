"""
계약 커버리지 — docs/api-spec.yaml에 선언된 (메서드, 경로)가 전부 실제 라우트로 존재하는가.

스펙엔 있는데 백엔드에 없는 엔드포인트는 프론트가 목 서버로 개발하다 실서버에 붙는 순간 404로
터진다(2026-09-29 실서버 스모크에서 counts·shortlist/order 두 개가 이렇게 발견됐다). DB가 필요
없는 정적 검사라 CI에서 가장 싸게 이 부류의 누락을 잡는다.

KNOWN_MISSING은 "알고 있고 이슈로 추적 중인 누락"이다. 두 방향으로 강제한다:
- 새로 생긴 누락(목록에 없는 것)이 있으면 실패 — 스펙을 추가하고 구현을 잊은 경우.
- 목록에 있는데 이미 구현된 것이 있으면 실패 — 구현이 끝났으니 여기서 지우라는 신호.
"""

import re
from pathlib import Path

import yaml

from main import app

SPEC_PATH = Path(__file__).resolve().parents[2] / "docs" / "api-spec.yaml"
HTTP_METHODS = ("get", "post", "put", "patch", "delete")

# (method, 경로 — 파라미터는 {}로 정규화) -> 추적 이슈
KNOWN_MISSING: dict[tuple[str, str], str] = {
    ("delete", "/maps/{}"): "#369 지도 삭제 — 스펙 먼저, maps 구현은 같은 브랜치에서",
    ("delete", "/maps/{}/members/me"): "#369 지도 나가기 — 스펙 먼저, maps 구현은 같은 브랜치에서",
}

# 스펙에 없어도 되는 라우트(운영/문서용).
NOT_IN_SPEC = {"/health", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def _norm(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


def _spec_operations() -> set[tuple[str, str]]:
    spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    return {(m, _norm(p)) for p, ops in spec["paths"].items() for m in ops if m in HTTP_METHODS}


def _implemented_operations() -> set[tuple[str, str]]:
    return {
        (m.lower(), _norm(r.path))
        for r in app.routes
        for m in (getattr(r, "methods", None) or [])
        if m not in ("HEAD", "OPTIONS")
    }


def test_spec_endpoints_missing_from_backend_are_exactly_the_known_ones():
    missing = _spec_operations() - _implemented_operations()
    unexpected = missing - set(KNOWN_MISSING)
    stale = set(KNOWN_MISSING) - missing
    assert not unexpected, f"스펙에 있는데 백엔드에 없는 엔드포인트(추적 안 됨): {sorted(unexpected)}"
    assert not stale, f"이미 구현됐으니 KNOWN_MISSING에서 지운다: {sorted(stale)}"


def test_backend_has_no_undocumented_endpoints():
    """반대 방향 — 라우트를 만들고 스펙(=프론트 계약)에 안 적은 경우."""
    extra = {
        (m, p) for (m, p) in _implemented_operations() - _spec_operations()
        if p not in NOT_IN_SPEC
    }
    assert not extra, f"백엔드에는 있는데 docs/api-spec.yaml에 없는 엔드포인트: {sorted(extra)}"
