"""설정 한 곳. 환경(dev/test/prod)과 각 포트의 어댑터 모드를 여기서만 선언한다.

새 의존성은 넣지 않았다 — python-dotenv는 이미 requirements.txt에 있는데 아무도 안 부르고
있었다. 여기서 한 번 부르면 .env.example이 그제서야 실제로 쓰인다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, get_args

Environment = Literal["dev", "test", "prod"]
AdapterMode = Literal["dev", "real"]

_PORTS = ("places", "auth")
# 주의: "membership"은 여기 없다(issue #89) — maps.api.DbMembershipGateway가 유일한 구현이라
# dev/real을 오갈 대상 자체가 없다. authz/deps.py::get_membership_gateway가 직접 그 클래스를
# 쓴다(select() 안 거침).
# 주의: "events"는 여기 없다 — 이벤트 발행은 select()로 고르는 포트가 아니라
# common.events.record_event를 직접 부르는 평범한 함수 호출이라 dev/real 모드 개념이 없다
# (아래 MISSING_REAL 주석 참고, adapters.py 절).


class ConfigError(RuntimeError):
    """설정이 틀렸을 때 — 서버를 띄우지 않고 여기서 죽는다."""


_dotenv_loaded = False   # 테스트가 Settings.from_env()를 여러 번 직접 호출할 수 있어
                          # 실제로 메모이즈한다(2차 DeepSeek 재검수 지적 — 이름은 "once"인데
                          # 매번 파일을 다시 읽고 있었다).


def _load_dotenv_once() -> None:
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    _dotenv_loaded = True
    try:
        from dotenv import load_dotenv
    except ImportError:          # dotenv 없이도 환경변수만으로 동작해야 한다
        return
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=False)   # 실제 환경변수가 항상 이긴다(Cloud Run)


def _env(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def _mode(name: str, default: AdapterMode) -> AdapterMode:
    value = _env(name, default)
    if value not in get_args(AdapterMode):
        raise ConfigError(f"{name}={value!r} — 'dev' 또는 'real'만 쓴다")
    return value  # type: ignore[return-value]


@dataclass(frozen=True)
class Settings:
    environment: Environment
    database_url: str
    cors_allow_origins: tuple[str, ...]
    cors_allow_origin_regex: str | None
    session_secret: str
    places_mode: AdapterMode
    auth_mode: AdapterMode
    # auth 모듈 전용(#4) — "설정 한 곳" 원칙에 따라 os.getenv를 auth/service.py에서 직접
    # 부르지 않고 여기 추가한다. 기본값 ""는 dev에서 카카오 앱 없이도 서버가 뜨게 하기 위함 —
    # 실제 로그인 시도 시점에야 카카오 API가 400/401을 돌려주며 실패한다(여기서 미리 막지
    # 않는다 — prod 가드는 __post_init__ 아래 참고).
    kakao_client_id: str = ""
    kakao_client_secret: str = ""
    kakao_redirect_uri: str = ""
    # FE 오리진의 정본(루트 확정, 2026-09-23) — maps의 "초대 링크 URL" 갭과 auth의 로그인
    # 리다이렉트 갭이 같은 원인(FE 오리진을 몰라 백엔드 자신의 주소로 대체)이라 여기 하나로
    # 합쳤다. dev 기본값은 Vite 개발 서버 주소. prod는 빈 값이면 아래 __post_init__이 막는다.
    frontend_base_url: str = ""
    # 로그인 성공 후 리다이렉트할 FE 진입점. 명시적으로 설정하지 않으면 frontend_base_url
    # 기준으로 파생된다(from_env 참고) — frontend_base_url도 없으면 예전처럼 상대경로 "/".
    frontend_login_redirect_url: str = "/"

    def __post_init__(self) -> None:
        # 잘못된 Settings는 애초에 "만들어질 수 없다" — 호출 순서에 기대지 않는 게 핵심이다.
        if self.environment not in get_args(Environment):
            raise ConfigError(f"PINGO_ENV={self.environment!r} — dev|test|prod 중 하나여야 한다")
        if self.environment != "prod":
            return
        stubbed = [p for p in _PORTS if getattr(self, f"{p}_mode") == "dev"]
        if stubbed:
            raise ConfigError(
                "PINGO_ENV=prod인데 개발용 스텁이 선택됐다: "
                + ", ".join(f"{p}({p.upper()}_MODE=dev)" for p in stubbed)
                + " — 실구현이 준비될 때까지 prod로 띄우지 않는다."
            )
        if "*" in self.cors_allow_origins:
            raise ConfigError("prod에서 CORS_ALLOW_ORIGINS=* 는 금지다 — 쿠키 인증이라 브라우저가 거부한다")
        if self.cors_allow_origin_regex:
            # 의도적으로 조용히 무시하지 않고 막는다: 개발용 .env를 그대로 복사해 배포하면
            # 이 값이 남아있기 쉬운데, 조용히 무시하면 "왜 CORS가 이상하게 관대하지"를 나중에
            # 디버깅해야 한다. 지금 시끄럽게 막는 게 그때 조용히 새는 것보다 싸다(DeepSeek
            # 검수가 "개발자가 헷갈릴 수 있다"고 지적했지만, 이 프로젝트의 기존 철학 —
            # common/errors.py의 catch-all처럼 실패를 감추지 않는다 — 과 일치시켜 그대로 둔다).
            raise ConfigError("prod에서는 CORS_ALLOW_ORIGIN_REGEX 대신 도메인을 명시한다")
        if not self.cors_allow_origins:
            # 둘 다 비어 있으면 모든 크로스 오리진 요청이 막힌다 — 의도했을 수도 있지만(백엔드
            # 전용 API 게이트웨이 뒤라서 FE가 같은 오리진), 조용히 그렇게 두면 "배포했는데 FE가
            # 아무것도 못 부른다"는 버그로 처음 발견된다. prod에서는 명시적으로 값을 요구한다.
            raise ConfigError("prod에서 CORS_ALLOW_ORIGINS가 비어있다 — FE 도메인을 명시한다")
        if self.session_secret in ("", "change-me-before-deploy"):
            raise ConfigError("prod에서 SESSION_SECRET이 기본값이다")
        if not self.frontend_base_url:
            raise ConfigError("prod에서 FRONTEND_BASE_URL이 비어있다 — 초대 링크·로그인 리다이렉트가 백엔드 자신의 주소로 샌다")

    @property
    def is_prod(self) -> bool:
        return self.environment == "prod"

    def mode_for(self, port: str) -> AdapterMode:
        return getattr(self, f"{port}_mode")

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv_once()
        environment = _env("PINGO_ENV", "dev")
        # prod에서는 "안 정했으면 dev"가 아니라 "안 정했으면 real"이다 —
        # 환경변수 하나 빠뜨렸다고 스텁이 조용히 올라가면 안 된다.
        default_mode: AdapterMode = "real" if environment == "prod" else "dev"
        origins = tuple(o.strip() for o in _env("CORS_ALLOW_ORIGINS", "").split(",") if o.strip())
        regex = _env("CORS_ALLOW_ORIGIN_REGEX",
                     "" if environment == "prod" else r"http://(localhost|127\.0\.0\.1)(:\d+)?")
        frontend_base_url = _env("FRONTEND_BASE_URL", "" if environment == "prod" else "http://localhost:5173").rstrip("/")
        return cls(
            environment=environment,  # type: ignore[arg-type]
            # 기본값 문자열은 common/database.py·alembic/env.py·pins/tests/conftest.py와 글자까지 같다.
            database_url=_env("DATABASE_URL", "postgresql://pingo:pingo@localhost:5432/pingo"),
            cors_allow_origins=origins,
            cors_allow_origin_regex=regex or None,
            session_secret=_env("SESSION_SECRET", "change-me-before-deploy"),
            places_mode=_mode("PLACES_MODE", default_mode),
            auth_mode=_mode("AUTH_MODE", default_mode),
            kakao_client_id=_env("KAKAO_CLIENT_ID", ""),
            kakao_client_secret=_env("KAKAO_CLIENT_SECRET", ""),
            kakao_redirect_uri=_env("KAKAO_REDIRECT_URI", ""),
            frontend_base_url=frontend_base_url,
            frontend_login_redirect_url=_env(
                "FRONTEND_LOGIN_REDIRECT_URL",
                f"{frontend_base_url}/" if frontend_base_url else "/",
            ),
        )


settings = Settings.from_env()
