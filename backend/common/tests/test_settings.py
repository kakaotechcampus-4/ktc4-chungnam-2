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
        llm_mode="real",
        frontend_base_url="https://app.pingo.example",
    )
    base.update(overrides)
    return Settings(**base)


def test_prod_refuses_dev_stub():
    with pytest.raises(ConfigError, match="places"):
        _settings(places_mode="dev")


def test_prod_refuses_llm_dev_stub():
    with pytest.raises(ConfigError, match="llm"):
        _settings(llm_mode="dev")


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


def test_prod_refuses_empty_frontend_base_url():
    with pytest.raises(ConfigError, match="FRONTEND_BASE_URL"):
        _settings(frontend_base_url="")


def test_non_prod_environment_allows_dev_stubs_and_wildcard():
    s = Settings(
        environment="dev",
        database_url="postgresql://x/y",
        cors_allow_origins=("*",),
        cors_allow_origin_regex=None,
        session_secret="change-me-before-deploy",
        places_mode="dev",
    )
    assert s.is_prod is False
    assert s.mode_for("places") == "dev"


def test_from_env_defaults_to_dev_mode_outside_prod(monkeypatch):
    monkeypatch.setenv("PINGO_ENV", "dev")
    monkeypatch.delenv("PLACES_MODE", raising=False)

    s = Settings.from_env()

    assert s.places_mode == "dev"


def test_from_env_defaults_to_real_mode_in_prod(monkeypatch):
    monkeypatch.setenv("PINGO_ENV", "prod")
    monkeypatch.delenv("PLACES_MODE", raising=False)
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://pingo.example")
    monkeypatch.setenv("SESSION_SECRET", "a-real-secret")
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://app.pingo.example")

    s = Settings.from_env()

    assert s.places_mode == "real"


def test_from_env_dev_regex_default_is_localhost_only(monkeypatch):
    monkeypatch.setenv("PINGO_ENV", "dev")
    monkeypatch.delenv("CORS_ALLOW_ORIGIN_REGEX", raising=False)

    s = Settings.from_env()

    assert s.cors_allow_origin_regex is not None
    assert "localhost" in s.cors_allow_origin_regex


def test_from_env_dev_frontend_base_url_defaults_to_vite_dev_server(monkeypatch):
    monkeypatch.setenv("PINGO_ENV", "dev")
    monkeypatch.delenv("FRONTEND_BASE_URL", raising=False)
    monkeypatch.delenv("FRONTEND_LOGIN_REDIRECT_URL", raising=False)

    s = Settings.from_env()

    assert s.frontend_base_url == "http://localhost:5173"
    assert s.frontend_login_redirect_url == "http://localhost:5173/"


def test_from_env_frontend_login_redirect_url_explicit_overrides_derived(monkeypatch):
    monkeypatch.setenv("PINGO_ENV", "dev")
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://app.pingo.example")
    monkeypatch.setenv("FRONTEND_LOGIN_REDIRECT_URL", "https://app.pingo.example/login/callback")

    s = Settings.from_env()

    assert s.frontend_login_redirect_url == "https://app.pingo.example/login/callback"


def test_from_env_prod_has_no_regex_default(monkeypatch):
    monkeypatch.setenv("PINGO_ENV", "prod")
    monkeypatch.delenv("CORS_ALLOW_ORIGIN_REGEX", raising=False)
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://pingo.example")
    monkeypatch.setenv("SESSION_SECRET", "a-real-secret")
    monkeypatch.setenv("PLACES_MODE", "real")
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://app.pingo.example")

    s = Settings.from_env()

    assert s.cors_allow_origin_regex is None


def test_invalid_adapter_mode_is_rejected(monkeypatch):
    monkeypatch.setenv("PINGO_ENV", "dev")
    monkeypatch.setenv("PLACES_MODE", "bogus")

    with pytest.raises(ConfigError, match="PLACES_MODE"):
        Settings.from_env()


def test_from_env_llm_defaults_outside_prod(monkeypatch):
    monkeypatch.setenv("PINGO_ENV", "dev")
    for name in ("LLM_MODE", "LLM_MODEL", "ELICE_ML_API_BASE_URL", "ELICE_ML_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    s = Settings.from_env()

    assert s.llm_mode == "dev"
    assert s.llm_model == "gpt-5.6-luna"
    assert s.elice_ml_api_base_url == ""
    assert s.elice_ml_api_key == ""
    assert s.mode_for("llm") == "dev"


def test_from_env_llm_mode_defaults_to_real_in_prod(monkeypatch):
    monkeypatch.setenv("PINGO_ENV", "prod")
    monkeypatch.delenv("LLM_MODE", raising=False)
    monkeypatch.setenv("PLACES_MODE", "real")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://pingo.example")
    monkeypatch.setenv("SESSION_SECRET", "a-real-secret")
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://app.pingo.example")

    assert Settings.from_env().llm_mode == "real"


def test_from_env_prod_with_llm_mode_dev_is_refused(monkeypatch):
    monkeypatch.setenv("PINGO_ENV", "prod")
    monkeypatch.setenv("LLM_MODE", "dev")
    monkeypatch.setenv("PLACES_MODE", "real")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://pingo.example")
    monkeypatch.setenv("SESSION_SECRET", "a-real-secret")
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://app.pingo.example")

    with pytest.raises(ConfigError, match="llm"):
        Settings.from_env()


def test_from_env_reads_llm_overrides(monkeypatch):
    monkeypatch.setenv("PINGO_ENV", "dev")
    monkeypatch.setenv("LLM_MODE", "real")
    monkeypatch.setenv("LLM_MODEL", "other-model")
    monkeypatch.setenv("ELICE_ML_API_BASE_URL", "https://ml.example/v1")
    monkeypatch.setenv("ELICE_ML_API_KEY", "k")

    s = Settings.from_env()

    assert (s.llm_mode, s.llm_model) == ("real", "other-model")
    assert (s.elice_ml_api_base_url, s.elice_ml_api_key) == ("https://ml.example/v1", "k")


def test_from_env_kakao_rest_key_falls_back_to_client_id(monkeypatch):
    monkeypatch.setenv("PINGO_ENV", "dev")
    monkeypatch.delenv("KAKAO_REST_API_KEY", raising=False)
    monkeypatch.setenv("KAKAO_CLIENT_ID", "client-id")
    assert Settings.from_env().kakao_rest_api_key == "client-id"
    monkeypatch.setenv("KAKAO_REST_API_KEY", "rest-key")
    assert Settings.from_env().kakao_rest_api_key == "rest-key"


def test_from_env_places_keys_default_to_empty(monkeypatch):
    monkeypatch.setenv("PINGO_ENV", "dev")
    for name in ("NAVER_SEARCH_CLIENT_ID", "NAVER_SEARCH_CLIENT_SECRET", "GOOGLE_PLACES_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    s = Settings.from_env()
    assert (s.naver_search_client_id, s.naver_search_client_secret, s.google_places_api_key) == ("", "", "")


def test_from_env_without_pingo_env_is_prod(monkeypatch):
    """PINGO_ENV를 빠뜨려도 가장 엄격한 쪽이다(#126) — 배포에서 변수 하나 놓쳤다고 개발용 설정이 올라가면 안 된다."""
    monkeypatch.delenv("PINGO_ENV", raising=False)
    monkeypatch.setenv("PLACES_MODE", "real")
    monkeypatch.setenv("LLM_MODE", "real")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://pingo.example")
    monkeypatch.setenv("SESSION_SECRET", "a-real-secret")
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://app.pingo.example")

    s = Settings.from_env()

    assert s.is_prod
    assert (s.places_mode, s.llm_mode) == ("real", "real")


def test_from_env_without_pingo_env_runs_prod_guards(monkeypatch):
    """PINGO_ENV 없이 SESSION_SECRET도 안 정하면 prod 가드가 서버를 세운다 — 쿠키만으로 로그인되는 경로는 이제 없다."""
    monkeypatch.delenv("PINGO_ENV", raising=False)
    monkeypatch.setenv("PLACES_MODE", "real")
    monkeypatch.setenv("LLM_MODE", "real")
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://pingo.example")
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://app.pingo.example")

    with pytest.raises(ConfigError, match="SESSION_SECRET"):
        Settings.from_env()
