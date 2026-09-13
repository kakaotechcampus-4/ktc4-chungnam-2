"""common/settings.py 테스트.

두 종류를 분리한다 — 서로 다른 걸 검증하므로 섞지 않는다(DeepSeek 검수 지적):
- `__post_init__` 가드: `Settings(...)`를 직접 생성해 확인한다. 모듈 싱글턴과 무관하게
  격리돼 있어 안전하다.
- `from_env()`의 기본값 분기: 모듈 레벨 `settings` 싱글턴을 건드리거나 reload할 필요 없이,
  `monkeypatch.setenv(...)` 후 `Settings.from_env()`를 직접 호출해 반환값을 assert한다.
"""

import pytest

from common.settings import ConfigError, Settings


def _settings(**overrides):
    base = dict(
        environment="prod",
        database_url="postgresql://x/y",
        cors_allow_origins=("https://pingo.example",),
        cors_allow_origin_regex=None,
        session_secret="real-secret",
        places_mode="real",
        membership_mode="real",
        auth_mode="real",
    )
    base.update(overrides)
    return Settings(**base)


def test_prod_refuses_dev_stub():
    with pytest.raises(ConfigError, match="places"):
        _settings(places_mode="dev")


def test_prod_refuses_wildcard_cors_origin():
    with pytest.raises(ConfigError, match="CORS_ALLOW_ORIGINS"):
        _settings(cors_allow_origins=("*",))


def test_prod_refuses_cors_origin_regex():
    with pytest.raises(ConfigError, match="CORS_ALLOW_ORIGIN_REGEX"):
        _settings(cors_allow_origin_regex="http://localhost")


def test_prod_refuses_default_session_secret():
    with pytest.raises(ConfigError, match="SESSION_SECRET"):
        _settings(session_secret="change-me-before-deploy")


def test_unknown_environment_is_rejected():
    with pytest.raises(ConfigError, match="staging"):
        _settings(environment="staging")


def test_prod_refuses_empty_cors_origins_with_no_regex():
    with pytest.raises(ConfigError, match="CORS_ALLOW_ORIGINS"):
        _settings(cors_allow_origins=(), cors_allow_origin_regex=None)


def test_non_prod_environment_allows_dev_stubs_and_wildcard():
    s = Settings(
        environment="dev",
        database_url="postgresql://x/y",
        cors_allow_origins=("*",),
        cors_allow_origin_regex=None,
        session_secret="change-me-before-deploy",
        places_mode="dev",
        membership_mode="dev",
        auth_mode="dev",
    )
    assert s.is_prod is False
    assert s.mode_for("places") == "dev"


def test_from_env_defaults_to_dev_mode_outside_prod(monkeypatch):
    monkeypatch.setenv("PINGO_ENV", "dev")
    monkeypatch.delenv("PLACES_MODE", raising=False)
    monkeypatch.delenv("MEMBERSHIP_MODE", raising=False)
    monkeypatch.delenv("AUTH_MODE", raising=False)

    s = Settings.from_env()

    assert s.places_mode == "dev"
    assert s.membership_mode == "dev"
    assert s.auth_mode == "dev"


def test_from_env_defaults_to_real_mode_in_prod(monkeypatch):
    monkeypatch.setenv("PINGO_ENV", "prod")
    monkeypatch.delenv("PLACES_MODE", raising=False)
    monkeypatch.delenv("MEMBERSHIP_MODE", raising=False)
    monkeypatch.delenv("AUTH_MODE", raising=False)
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://pingo.example")
    monkeypatch.setenv("SESSION_SECRET", "a-real-secret")

    s = Settings.from_env()

    assert s.places_mode == "real"
    assert s.membership_mode == "real"
    assert s.auth_mode == "real"


def test_from_env_dev_regex_default_is_localhost_only(monkeypatch):
    monkeypatch.setenv("PINGO_ENV", "dev")
    monkeypatch.delenv("CORS_ALLOW_ORIGIN_REGEX", raising=False)

    s = Settings.from_env()

    assert s.cors_allow_origin_regex is not None
    assert "localhost" in s.cors_allow_origin_regex


def test_from_env_prod_has_no_regex_default(monkeypatch):
    monkeypatch.setenv("PINGO_ENV", "prod")
    monkeypatch.delenv("CORS_ALLOW_ORIGIN_REGEX", raising=False)
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://pingo.example")
    monkeypatch.setenv("SESSION_SECRET", "a-real-secret")
    monkeypatch.setenv("PLACES_MODE", "real")
    monkeypatch.setenv("MEMBERSHIP_MODE", "real")
    monkeypatch.setenv("AUTH_MODE", "real")

    s = Settings.from_env()

    assert s.cors_allow_origin_regex is None


def test_invalid_adapter_mode_is_rejected(monkeypatch):
    monkeypatch.setenv("PINGO_ENV", "dev")
    monkeypatch.setenv("PLACES_MODE", "bogus")

    with pytest.raises(ConfigError, match="PLACES_MODE"):
        Settings.from_env()
