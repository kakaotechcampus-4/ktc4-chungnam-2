"""관찰 tick 명령(#812) — run_tick을 한 번 돌리고 끝난다. 실패하면 종료 코드 1."""

from agent import flows, tick


def test_main_runs_tick_once_and_returns_zero(monkeypatch):
    calls = []
    monkeypatch.setattr(flows, "run_tick", lambda now: calls.append(now))

    assert tick.main() == 0
    assert len(calls) == 1 and calls[0].tzinfo is not None


def test_main_returns_one_and_logs_only_the_class_name_when_tick_fails(monkeypatch, caplog):
    def boom(now):
        raise RuntimeError("secret-detail")

    monkeypatch.setattr(flows, "run_tick", boom)

    with caplog.at_level("ERROR", logger="pingo.agent"):
        assert tick.main() == 1
    assert "RuntimeError" in caplog.text and "secret-detail" not in caplog.text
