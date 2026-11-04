"""common/settings.py 테스트.

두 종류를 분리한다 — 서로 다른 걸 검증하므로 섞지 않는다(DeepSeek 검수 지적):
- `__post_init__` 가드: `Settings(...)`를 직접 생성해 확인한다. 모듈 싱글턴과 무관하게
  격리돼 있어 안전하다.
- `from_env()`의 기본값 분기: 모듈 레벨 `settings` 싱글턴을 건드리거나 reload할 필요 없이,
  `monkeypatch.setenv(...)` 후 `Settings.from_env()`를 직접 호출해 반환값을 assert한다.
"""

import pytest

from common.settings import ConfigError, Settings


_TLS_DB_URL = "postgresql://app:db-password-1@db.internal:5432/y?sslmode=require"
_STRONG_SECRET = "s" * 40   # MIN_SESSION_SECRET_LEN(32) 이상

_EXTERNAL_KEYS = {
    "KAKAO_REST_API_KEY": "rest-key",
    "ELICE_ML_API_BASE_URL": "https://ml.example", "ELICE_ML_API_KEY": "elice-key",
}


@pytest.fixture(autouse=True)
def _nothing_decided(monkeypatch):
    """conftest가 PLACES_MODE·LLM_MODE를 dev로 고정해 둔다(#370) — 여기서는 "아무것도 정하지 않은 상태"를
    직접 만든다. 모드를 정하는 테스트는 각자 setenv한다."""
    for name in ("PLACES_MODE", "LLM_MODE", "LOG_LEVEL", "PLACES_SOURCES",
                 "KAKAO_CLIENT_ID", "KAKAO_CLIENT_SECRET", "KAKAO_REDIRECT_URI",
                 "NAVER_SEARCH_CLIENT_ID", "NAVER_SEARCH_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    # 실제 모드의 외부 키(#810) — 키가 비는 경우만 각 테스트가 지운다.
    for name, value in _EXTERNAL_KEYS.items():
        monkeypatch.setenv(name, value)
    for name in ("DB_POOL_SIZE", "DB_MAX_OVERFLOW", "DB_POOL_PRE_PING", "DB_POOL_RECYCLE_S", "COOKIE_SECURE"):
        monkeypatch.delenv(name, raising=False)


def _settings(**overrides):
    base = dict(
        environment="prod",
        database_url=_TLS_DB_URL,
        cors_allow_origins=("https://pingo.example",),
        cors_allow_origin_regex=None,
        session_secret=_STRONG_SECRET,
        places_mode="real",
        llm_mode="real",
        frontend_base_url="https://app.pingo.example",
        kakao_rest_api_key="rest-key",
        elice_ml_api_base_url="https://ml.example", elice_ml_api_key="elice-key",
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
    with pytest.raises(ConfigError, match="stage"):
        _settings(environment="stage")


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
    monkeypatch.setenv("SESSION_SECRET", _STRONG_SECRET)
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
    monkeypatch.setenv("SESSION_SECRET", _STRONG_SECRET)
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
    assert s.llm_model == "gpt-6-luna"
    assert s.elice_ml_api_base_url == ""
    assert s.elice_ml_api_key == ""
    assert s.mode_for("llm") == "dev"


def test_from_env_llm_mode_defaults_to_real_in_prod(monkeypatch):
    monkeypatch.setenv("PINGO_ENV", "prod")
    monkeypatch.delenv("LLM_MODE", raising=False)
    monkeypatch.setenv("PLACES_MODE", "real")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://pingo.example")
    monkeypatch.setenv("SESSION_SECRET", _STRONG_SECRET)
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://app.pingo.example")

    assert Settings.from_env().llm_mode == "real"


def test_from_env_prod_with_llm_mode_dev_is_refused(monkeypatch):
    monkeypatch.setenv("PINGO_ENV", "prod")
    monkeypatch.setenv("LLM_MODE", "dev")
    monkeypatch.setenv("PLACES_MODE", "real")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://pingo.example")
    monkeypatch.setenv("SESSION_SECRET", _STRONG_SECRET)
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
    for name in ("NAVER_SEARCH_CLIENT_ID", "NAVER_SEARCH_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    s = Settings.from_env()
    assert (s.naver_search_client_id, s.naver_search_client_secret) == ("", "")


def test_from_env_without_pingo_env_is_prod(monkeypatch):
    """PINGO_ENV를 빠뜨려도 가장 엄격한 쪽이다(#126) — 배포에서 변수 하나 놓쳤다고 개발용 설정이 올라가면 안 된다."""
    monkeypatch.delenv("PINGO_ENV", raising=False)
    monkeypatch.setenv("PLACES_MODE", "real")
    monkeypatch.setenv("LLM_MODE", "real")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://pingo.example")
    monkeypatch.setenv("SESSION_SECRET", _STRONG_SECRET)
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


def test_log_level_defaults_to_info_and_reads_env(monkeypatch):
    monkeypatch.setenv("PINGO_ENV", "dev")
    assert Settings.from_env().log_level == "INFO"

    monkeypatch.setenv("LOG_LEVEL", "debug")
    assert Settings.from_env().log_level == "DEBUG"


def test_invalid_log_level_is_rejected(monkeypatch):
    monkeypatch.setenv("PINGO_ENV", "dev")
    monkeypatch.setenv("LOG_LEVEL", "loud")

    with pytest.raises(ConfigError, match="LOG_LEVEL"):
        Settings.from_env()


def test_main_quiets_http_client_loggers():
    """httpx는 INFO에서 요청 주소(엘리스 경로 id, 사용자 검색어)를 찍는다 — 앱을 올리면 경고부터만 남긴다."""
    import logging

    import main  # noqa: F401  (import 시 로깅을 설정한다)

    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


def test_agent_loop_is_off_by_default(monkeypatch):
    monkeypatch.setenv("PINGO_ENV", "dev")
    monkeypatch.delenv("AGENT_LOOP_IN_PROCESS", raising=False)
    assert Settings.from_env().agent_loop_in_process is False


@pytest.mark.parametrize("raw, expected", [("1", True), ("true", True), ("TRUE", True), ("0", False), ("no", False)])
def test_agent_loop_reads_env(monkeypatch, raw, expected):
    monkeypatch.setenv("PINGO_ENV", "dev")
    monkeypatch.setenv("AGENT_LOOP_IN_PROCESS", raw)
    assert Settings.from_env().agent_loop_in_process is expected


# ---- staging(#788): prod와 같은 가드, QA 로그인 비밀값 ----


@pytest.mark.parametrize("overrides, match", [
    ({"places_mode": "dev"}, "places"),
    ({"llm_mode": "dev"}, "llm"),
    ({"cors_allow_origins": ("*",)}, "CORS_ALLOW_ORIGINS"),
    ({"cors_allow_origin_regex": "http://localhost"}, "CORS_ALLOW_ORIGIN_REGEX"),
    ({"cors_allow_origins": ()}, "CORS_ALLOW_ORIGINS"),
    ({"session_secret": "change-me-before-deploy"}, "SESSION_SECRET"),
    ({"session_secret": ""}, "SESSION_SECRET"),
    ({"frontend_base_url": ""}, "FRONTEND_BASE_URL"),
])
def test_staging_gets_the_prod_guards(overrides, match):
    with pytest.raises(ConfigError, match=match):
        _settings(environment="staging", **overrides)


def test_staging_with_strict_values_starts():
    s = _settings(environment="staging", qa_login_secret="qa")

    assert s.is_prod is False   # is_prod는 운영만이다(어댑터 2차 검사)
    assert s.qa_login_enabled is True


def test_prod_refuses_qa_login_secret():
    with pytest.raises(ConfigError, match="QA_LOGIN_SECRET"):
        _settings(qa_login_secret="qa")


def test_from_env_prod_with_qa_login_secret_is_refused(monkeypatch):
    monkeypatch.setenv("PINGO_ENV", "prod")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://pingo.example")
    monkeypatch.setenv("SESSION_SECRET", _STRONG_SECRET)
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://app.pingo.example")
    monkeypatch.setenv("QA_LOGIN_SECRET", "qa")

    with pytest.raises(ConfigError, match="QA_LOGIN_SECRET"):
        Settings.from_env()


@pytest.mark.parametrize("environment, secret, expected", [
    ("staging", "qa", True),
    ("staging", "", False),
    ("prod", "", False),
    ("dev", "qa", False),
    ("test", "qa", False),
])
def test_qa_login_is_enabled_only_in_staging_with_a_secret(environment, secret, expected):
    assert _settings(environment=environment, qa_login_secret=secret).qa_login_enabled is expected


def _staging_env(monkeypatch):
    monkeypatch.setenv("PINGO_ENV", "staging")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://staging.pingo.example")
    monkeypatch.setenv("SESSION_SECRET", _STRONG_SECRET)
    monkeypatch.setenv("DATABASE_URL", _TLS_DB_URL)
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://staging.pingo.example")
    for name in ("CORS_ALLOW_ORIGIN_REGEX", "QA_LOGIN_SECRET"):
        monkeypatch.delenv(name, raising=False)


def test_from_env_staging_uses_the_strict_defaults(monkeypatch):
    _staging_env(monkeypatch)
    monkeypatch.setenv("QA_LOGIN_SECRET", "qa")

    s = Settings.from_env()

    assert (s.places_mode, s.llm_mode) == ("real", "real")
    assert s.cors_allow_origin_regex is None
    assert s.qa_login_secret == "qa" and s.qa_login_enabled


def test_from_env_staging_without_qa_login_secret_has_qa_login_off(monkeypatch):
    _staging_env(monkeypatch)

    assert Settings.from_env().qa_login_enabled is False


def test_from_env_staging_has_no_frontend_base_url_default(monkeypatch):
    _staging_env(monkeypatch)
    monkeypatch.delenv("FRONTEND_BASE_URL")

    with pytest.raises(ConfigError, match="FRONTEND_BASE_URL"):
        Settings.from_env()


def test_from_env_staging_refuses_default_session_secret(monkeypatch):
    _staging_env(monkeypatch)
    monkeypatch.delenv("SESSION_SECRET")

    with pytest.raises(ConfigError, match="SESSION_SECRET"):
        Settings.from_env()


# ---- 기동 가드: 실제 모드의 외부 키(#810) ----


@pytest.mark.parametrize("environment", ["staging", "prod"])
@pytest.mark.parametrize("overrides, match", [
    ({"kakao_rest_api_key": ""}, "KAKAO_REST_API_KEY"),
    ({"elice_ml_api_base_url": ""}, "ELICE_ML_API_BASE_URL"),
    ({"elice_ml_api_key": ""}, "ELICE_ML_API_KEY"),
])
def test_strict_environments_refuse_empty_external_keys(environment, overrides, match):
    with pytest.raises(ConfigError, match=match):
        _settings(environment=environment, **overrides)


def test_dev_and_test_allow_empty_external_keys():
    for environment in ("dev", "test"):
        for mode in ("dev", "real"):
            _settings(environment=environment, places_mode=mode, llm_mode=mode,
                      kakao_rest_api_key="", elice_ml_api_base_url="", elice_ml_api_key="",
                      places_sources=("kakao", "naver"))


def test_from_env_staging_refuses_empty_kakao_key(monkeypatch):
    _staging_env(monkeypatch)
    monkeypatch.delenv("KAKAO_REST_API_KEY")

    with pytest.raises(ConfigError, match="KAKAO_REST_API_KEY"):
        Settings.from_env()


@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_kakao_search_does_not_require_oauth_settings(environment):
    _settings(environment=environment, kakao_client_id="", kakao_client_secret="", kakao_redirect_uri="")


@pytest.mark.parametrize("environment", ["staging", "prod", "dev", "test"])
@pytest.mark.parametrize("rest_key, expected", [("", "client-key"), (" \t ", "client-key"), (" rest-key ", "rest-key")])
def test_direct_settings_resolve_the_key_given_to_kakao_adapter(environment, rest_key, expected):
    s = _settings(environment=environment, kakao_client_id=" client-key ", kakao_rest_api_key=rest_key)
    assert s.kakao_rest_api_key == expected


@pytest.mark.parametrize("environment", ["staging", "prod"])
@pytest.mark.parametrize("field", ["naver_search_client_id", "naver_search_client_secret"])
@pytest.mark.parametrize("blank", ["", " \t\n "])
def test_selected_naver_requires_both_search_keys(environment, field, blank):
    values = dict(naver_search_client_id="naver-id", naver_search_client_secret="naver-secret")
    values[field] = blank
    with pytest.raises(ConfigError, match=field.upper()) as exc:
        _settings(environment=environment, places_sources=("kakao", "naver"), **values)
    assert "naver-secret" not in str(exc.value)


@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_unselected_sources_do_not_require_keys(environment):
    _settings(environment=environment, places_sources=("naver",), kakao_rest_api_key="",
              kakao_client_id="", kakao_client_secret="", kakao_redirect_uri="",
              naver_search_client_id="naver-id", naver_search_client_secret="naver-secret")


@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_strict_from_env_accepts_kakao_client_id_fallback(monkeypatch, environment):
    _staging_env(monkeypatch)
    monkeypatch.setenv("PINGO_ENV", environment)
    monkeypatch.setenv("KAKAO_REST_API_KEY", " \t ")
    monkeypatch.setenv("KAKAO_CLIENT_ID", "fallback-key")
    assert Settings.from_env().kakao_rest_api_key == "fallback-key"


@pytest.mark.parametrize("name", ["NAVER_SEARCH_CLIENT_ID", "NAVER_SEARCH_CLIENT_SECRET"])
def test_selected_naver_from_env_refuses_missing_search_key(monkeypatch, name):
    _staging_env(monkeypatch)
    monkeypatch.setenv("PLACES_SOURCES", "naver")
    monkeypatch.setenv("NAVER_SEARCH_CLIENT_ID", "naver-id")
    monkeypatch.setenv("NAVER_SEARCH_CLIENT_SECRET", "naver-secret")
    monkeypatch.delenv(name)
    with pytest.raises(ConfigError, match=name):
        Settings.from_env()


# ---- DB 풀, 쿠키 Secure(#810) ----


def test_from_env_pool_defaults_match_sqlalchemy_defaults():
    s = Settings.from_env()

    assert (s.db_pool_size, s.db_max_overflow, s.db_pool_pre_ping, s.db_pool_recycle_s) == (5, 10, True, -1)


def test_from_env_reads_pool_overrides(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE", "3")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "2")
    monkeypatch.setenv("DB_POOL_PRE_PING", "0")
    monkeypatch.setenv("DB_POOL_RECYCLE_S", "1800")

    s = Settings.from_env()

    assert (s.db_pool_size, s.db_max_overflow, s.db_pool_pre_ping, s.db_pool_recycle_s) == (3, 2, False, 1800)


def test_pool_values_reach_the_engine():
    from common.database import engine
    from common.settings import settings

    assert engine.pool.size() == settings.db_pool_size
    assert engine.pool._max_overflow == settings.db_max_overflow
    assert engine.pool._pre_ping is settings.db_pool_pre_ping
    assert engine.pool._recycle == settings.db_pool_recycle_s


def test_pool_overrides_reach_a_new_engine(monkeypatch):
    import importlib
    import runpy
    from pathlib import Path

    settings_module = importlib.import_module("common.settings")
    monkeypatch.setattr(settings_module, "settings", _settings(
        environment="test", db_pool_size=3, db_max_overflow=2,
        db_pool_pre_ping=False, db_pool_recycle_s=1800,
    ))
    engine = runpy.run_path(str(Path(__file__).resolve().parents[1] / "database.py"))["engine"]
    try:
        assert (engine.pool.size(), engine.pool._max_overflow,
                engine.pool._pre_ping, engine.pool._recycle) == (3, 2, False, 1800)
    finally:
        engine.dispose()


def test_invalid_pool_value_is_rejected(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE", "many")

    with pytest.raises(ConfigError, match="DB_POOL_SIZE"):
        Settings.from_env()


@pytest.mark.parametrize("environment, expected", [("dev", False), ("test", False), ("staging", True), ("prod", True)])
def test_cookie_secure_default_follows_environment(monkeypatch, environment, expected):
    _staging_env(monkeypatch)
    monkeypatch.setenv("PINGO_ENV", environment)
    monkeypatch.setenv("PLACES_MODE", "real")
    monkeypatch.setenv("LLM_MODE", "real")

    assert Settings.from_env().cookie_secure is expected


def test_cookie_secure_can_be_turned_off_outside_strict_environments(monkeypatch):
    monkeypatch.setenv("PINGO_ENV", "dev")
    monkeypatch.setenv("COOKIE_SECURE", "0")

    assert Settings.from_env().cookie_secure is False   # staging·prod는 아래 가드(#1210)가 막는다


def test_invalid_cookie_secure_is_rejected(monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "maybe")

    with pytest.raises(ConfigError, match="COOKIE_SECURE"):
        Settings.from_env()


@pytest.mark.parametrize("field", [k.lower() for k in _EXTERNAL_KEYS])
@pytest.mark.parametrize("blank", ["   ", "\t", "\n", " \t\n "])
def test_real_mode_refuses_whitespace_only_external_key(field, blank):
    with pytest.raises(ConfigError, match=field.upper()) as exc:
        _settings(**{field: blank})

    assert "rest-key" not in str(exc.value) and "elice-key" not in str(exc.value)   # 오류에는 변수명만 든다


@pytest.mark.parametrize("name", list(_EXTERNAL_KEYS))
def test_from_env_refuses_whitespace_only_external_key(monkeypatch, name):
    monkeypatch.setenv("PINGO_ENV", "prod")
    monkeypatch.setenv("SESSION_SECRET", _STRONG_SECRET)
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://pingo.example")
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://app.pingo.example")
    monkeypatch.setenv(name, " \t ")

    with pytest.raises(ConfigError, match=name):
        Settings.from_env()


@pytest.mark.parametrize("size,overflow,recycle", [(1, 0, -1), (1, 0, 1), (50, 100, 3600)])
def test_pool_boundary_values_are_accepted(size, overflow, recycle):
    s = _settings(db_pool_size=size, db_max_overflow=overflow, db_pool_recycle_s=recycle)

    assert (s.db_pool_size, s.db_max_overflow, s.db_pool_recycle_s) == (size, overflow, recycle)


@pytest.mark.parametrize("name,value", [
    ("DB_POOL_SIZE", "0"), ("DB_POOL_SIZE", "-1"),
    ("DB_MAX_OVERFLOW", "-1"), ("DB_MAX_OVERFLOW", "-2"),
    ("DB_POOL_RECYCLE_S", "0"), ("DB_POOL_RECYCLE_S", "-2"),
])
def test_pool_out_of_range_is_rejected(monkeypatch, name, value):
    monkeypatch.setenv("PINGO_ENV", "dev")
    monkeypatch.setenv(name, value)

    with pytest.raises(ConfigError, match=name):
        Settings.from_env()


@pytest.mark.parametrize("value", ["maybe", "2", "yes"])
def test_invalid_pool_pre_ping_is_rejected(monkeypatch, value):
    monkeypatch.setenv("DB_POOL_PRE_PING", value)

    with pytest.raises(ConfigError, match="DB_POOL_PRE_PING"):
        Settings.from_env()


# ---- 운영 설정 가드(#1210): strict에서만 막고 값은 오류에 싣지 않는다 ----

_SECRET_VALUES = ("db-password-1", "pw-in-url", "short-secret-value", "kakao-redirect-secret")


@pytest.mark.parametrize("environment", ["staging", "prod"])
@pytest.mark.parametrize("overrides, match", [
    ({"cookie_secure": False}, "COOKIE_SECURE"),
    ({"database_url": "postgresql://app:pw-in-url@db.internal:5432/y"}, "DATABASE_URL"),
    ({"database_url": "postgresql://app:pw-in-url@db.internal:5432/y?sslmode=prefer"}, "DATABASE_URL"),
    ({"database_url": "postgresql://app:pw-in-url@db.internal:5432/y?sslmode=disable"}, "DATABASE_URL"),
    ({"frontend_base_url": "http://app.pingo.example"}, "FRONTEND_BASE_URL"),
    ({"kakao_redirect_uri": "http://app.pingo.example/auth/kakao/callback"}, "KAKAO_REDIRECT_URI"),
    ({"kakao_redirect_uri": "https://api.other.example/auth/kakao/callback"}, "호스트"),
    ({"session_secret": "short-secret-value"}, "SESSION_SECRET"),
])
def test_strict_environments_refuse_unsafe_transport_settings(environment, overrides, match):
    with pytest.raises(ConfigError, match=match) as exc:
        _settings(environment=environment, **overrides)

    message = str(exc.value)
    assert not any(secret in message for secret in _SECRET_VALUES)
    for value in overrides.values():
        if isinstance(value, str):
            assert value not in message


@pytest.mark.parametrize("environment", ["dev", "test"])
def test_non_strict_environments_allow_the_same_settings(environment):
    s = _settings(
        environment=environment, cookie_secure=False,
        database_url="postgresql://app:pw-in-url@db.internal:5432/y",
        frontend_base_url="http://localhost:5173",
        kakao_redirect_uri="http://localhost:8000/auth/kakao/callback",
        session_secret="short",
    )

    assert s.cookie_secure is False


def test_strict_accepts_tls_db_and_matching_https_redirect():
    s = _settings(kakao_redirect_uri="https://app.pingo.example/api/auth/kakao/callback")

    assert s.kakao_redirect_uri.startswith("https://app.pingo.example")


@pytest.mark.parametrize("mode", ["require", "verify-ca", "verify-full"])
def test_strict_accepts_every_tls_sslmode(mode):
    assert _settings(database_url=f"postgresql://a:b@db.internal/y?sslmode={mode}")


def test_strict_allows_loopback_db_without_tls():
    assert _settings(database_url="postgresql://a:b@localhost:5432/y")


def test_session_secret_boundary():
    assert _settings(session_secret="s" * 32)
    with pytest.raises(ConfigError, match="SESSION_SECRET"):
        _settings(session_secret="s" * 31)


def test_from_env_prod_refuses_cookie_secure_off_without_echoing_secrets(monkeypatch):
    monkeypatch.setenv("PINGO_ENV", "prod")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://app.pingo.example")
    monkeypatch.setenv("SESSION_SECRET", _STRONG_SECRET)
    monkeypatch.setenv("DATABASE_URL", _TLS_DB_URL)
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://app.pingo.example")
    monkeypatch.setenv("COOKIE_SECURE", "0")

    with pytest.raises(ConfigError, match="COOKIE_SECURE") as exc:
        Settings.from_env()

    assert _STRONG_SECRET not in str(exc.value) and "db-password-1" not in str(exc.value)
