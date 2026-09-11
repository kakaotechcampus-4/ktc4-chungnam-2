"""포트 -> 구현 선택. 어댑터는 select()를 거치지 않고는 못 얻는다 — 그게 prod 가드가
우회될 수 없는 이유다. 선택 결과는 레지스트리에 쌓여 기동 로그에 한 번에 찍힌다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from common.settings import ConfigError, settings


@dataclass(frozen=True)
class Choice:
    port: str   # "pins.PlaceGateway"
    mode: str   # "dev" | "real"
    impl: str   # "pins.deps._dev_place_gateway"


_REGISTRY: dict[str, Choice] = {}   # port -> Choice. dict라 재import/재호출돼도 중복되지 않는다
                                     # (DeepSeek 검수 지적: list였으면 모듈이 재평가될 때마다 쌓임).


def select(
    port: str,
    mode: str,
    impls: Mapping[str, Callable[[], Any] | None],
    missing_real_issue: str | None = None,
) -> Callable[[], Any]:
    """FastAPI Depends에 넣을 팩토리를 고른다. import 시점에 평가되므로 서버가 뜨기 전에 터진다.

    2차 재검수(DeepSeek)에서 정확한 지적: `settings` 싱글턴은 이미 `__post_init__`에서
    prod+dev 조합을 막고 생성되므로, 각 모듈이 항상 `select(port, settings.<port>_mode, ...)`
    처럼 **싱글턴에서 읽은 mode**만 넘긴다면 아래 `is_prod and mode == "dev"` 체크는 절대
    참이 될 수 없는 죽은 코드다. 그럼에도 남겨두는 이유는 그 전제(항상 싱글턴에서 읽는다)가
    타입 시스템으로 강제되지 않기 때문이다 — `mode` 파라미터는 그냥 `str`이라, 누군가
    "일단 로컬에서 빨리 테스트하려고" `select("pins.PlaceGateway", "dev", {...})`처럼 문자열을
    하드코딩해 넣는 실수가 실제로 나올 수 있다(학생 팀에서 흔한 실수 유형). 이 체크는 정확히
    그 실수를 잡기 위한 것이지, `Settings.__post_init__` 우회를 막기 위한 게 아니다 —
    "2차 방어선"이라는 표현이 틀렸으므로 아래처럼 정정한다."""
    factory = impls.get(mode)
    if factory is None:
        if mode == "real":
            raise ConfigError(
                f"{port}: 실구현이 아직 없다"
                + (f" ({missing_real_issue})" if missing_real_issue else "")
                + f" — PINGO_ENV={settings.environment}"
            )
        raise ConfigError(f"{port}: mode={mode!r}에 해당하는 구현이 없다")
    if settings.is_prod and mode == "dev":
        # settings 싱글턴은 이미 prod+dev를 막고 생성되므로, mode가 settings.<port>_mode
        # 그대로라면 이 분기는 실행되지 않는다(그 경로는 이미 Settings() 생성 시점에 죽는다).
        # 이 체크가 실제로 잡는 것은 호출부가 mode를 하드코딩해 settings를 안 거친 경우다.
        raise ConfigError(f"{port}: prod에서 개발용 구현({getattr(factory, '__name__', repr(factory))})은 쓸 수 없다")
    # functools.partial 등 __qualname__이 없는 callable도 안전하게(Antigravity 검수 지적)
    impl_name = f"{getattr(factory, '__module__', '?')}.{getattr(factory, '__qualname__', repr(factory))}"
    _REGISTRY[port] = Choice(port, mode, impl_name)
    return factory


def assembly() -> list[Choice]:
    return sorted(_REGISTRY.values(), key=lambda c: c.port)


def format_assembly() -> str:
    lines = [f"[pingo] environment={settings.environment}"]
    for c in assembly():
        flag = "  <-- DEV STUB" if c.mode == "dev" else ""
        lines.append(f"[pingo]   {c.port:<28} {c.mode:<5} {c.impl}{flag}")
    return "\n".join(lines)
