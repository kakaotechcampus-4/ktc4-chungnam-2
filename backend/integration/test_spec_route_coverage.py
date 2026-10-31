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
    ("get", "/places/external-search"): "장소 검색 결과 없음의 카카오맵 링크 — 서버 구현 전(#903). 구현되면 지운다",
    ("get", "/credits/me"): "크레딧(#432) — credits 모듈 구현 전(#948). 구현되면 지운다",
    ("get", "/pins/{}/reviews"): "장소 후기(#432) — reviews 모듈 구현 전(#951). 구현되면 지운다",
    ("put", "/pins/{}/reviews/me"): "장소 후기(#432) — reviews 모듈 구현 전(#951). 구현되면 지운다",
    ("delete", "/pins/{}/reviews/me"): "장소 후기(#432) — reviews 모듈 구현 전(#951). 구현되면 지운다",
    ("post", "/reviews/{}/reports"): "장소 후기(#432) — reviews 모듈 구현 전(#951). 구현되면 지운다",
}

# 특정 환경에서만 붙는 경로 — main.py가 설정을 보고 include한다. 테스트 앱(PINGO_ENV=test)에는 없어야 한다.
ENV_ONLY: dict[tuple[str, str], str] = {
    ("post", "/auth/qa-login"): "스테이징 전용 QA 로그인(#788). staging 설정으로 만든 앱은 auth 테스트(#789)가 본다",
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
    missing = _spec_operations() - _implemented_operations() - set(ENV_ONLY)
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


def test_env_only_endpoints_are_not_mounted_in_the_test_app():
    """스테이징 전용 경로가 기본 앱에 붙어 있으면 prod에도 붙을 수 있다는 신호다."""
    mounted = set(ENV_ONLY) & _implemented_operations()
    assert not mounted, f"환경 전용 경로가 테스트 앱에 붙어 있다: {sorted(mounted)}"
