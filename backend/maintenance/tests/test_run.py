from datetime import datetime, timezone

from maintenance import run

NOW = datetime(2026, 10, 20, tzinfo=timezone.utc)


class FakeSession:
    def __init__(self, log):
        self.log = log

    def commit(self):
        self.log.append("commit")

    def rollback(self):
        self.log.append("rollback")

    def close(self):
        self.log.append("close")


def once(counts):
    """한 번 지우고 나면 빈 단계 — 되풀이 부르기가 두 번째에 멈춘다."""
    calls = []
    return lambda db, now: {} if calls else (calls.append(1) or counts)


def batched(total, batch, calls=None):
    """total행이 쌓여 있고 한 번에 batch행까지만 지우는 단계(각 모듈의 배치 상한 흉내)."""
    left = [total]

    def step(db, now):
        if calls is not None:
            calls.append(now)
        n = min(left[0], batch)
        left[0] -= n
        return {"rows": n}

    step.left = left
    return step


def _run(steps, argv=(), log=None):
    log = [] if log is None else log
    code = run.main(list(argv), session_factory=lambda: FakeSession(log), now=NOW, steps=steps)
    return code, log


def test_each_step_commits_and_reports(capsys):
    steps = {"a": once({"x": 2}), "b": once({"y": 1, "z": 3})}
    code, log = _run(steps)
    assert code == 0
    # 단계마다 한 번 지우고(commit), 한 번 더 불러 빈 걸 확인한다(commit)
    assert log == ["commit", "close", "commit", "close"] * 2
    out = capsys.readouterr().out
    assert "a: 2행" in out and "b: 4행" in out


def test_failed_step_does_not_block_others(capsys, caplog):
    def boom(db, now):
        raise ValueError("user@example.com")

    steps = {"a": boom, "b": once({"y": 1})}
    code, log = _run(steps)
    assert code == 1
    assert log == ["rollback", "close", "commit", "close", "commit", "close"]
    out = capsys.readouterr().out
    assert "a: 실패" in out and "b: 1행" in out
    assert "ValueError" in caplog.text and "user@example.com" not in caplog.text


def test_dry_run_rolls_back_every_step(capsys):
    steps = {"a": lambda db, now: {"x": 2}, "b": lambda db, now: {"y": 1}}   # 건수가 계속 나와도 dry-run은 한 번만 부른다
    code, log = _run(steps, ["--dry-run"])
    assert code == 0
    assert "commit" not in log and log.count("rollback") == 2
    assert "[dry-run]" in capsys.readouterr().out


def test_only_runs_one_step():
    called = []
    steps = {"a": lambda db, now: called.append("a") or {}, "b": lambda db, now: called.append("b") or {}}
    _run(steps, ["--only", "b"])
    assert called == ["b"]


def test_step_receives_now():
    seen = []
    _run({"a": lambda db, now: seen.append(now) or {}})
    assert seen == [NOW]


def test_default_steps_are_the_eight_stages():
    assert list(run.STEPS) == ["maps", "notifications", "guests", "llm_calls", "idempotency", "withdrawn", "events", "pins"]


def test_format_report_shows_map_count_apart_from_rows():
    out = run.format_report({"maps": run.StepResult({"deleted_maps": 2, "pins": 5, "maps": 2}, rounds=1)}, dry_run=False)
    assert "maps: 7행 (지도 2개)" in out


def test_pins_runs_in_full_and_only_modes(monkeypatch):
    from pins import api as pins_api

    calls = []
    monkeypatch.setattr(pins_api, "purge_deleted_pins", lambda db, *, now: calls.append(now) or {})
    steps = {name: (step if name == "pins" else lambda db, now: {}) for name, step in run.STEPS.items()}
    assert _run(steps)[0] == 0
    assert _run(steps, ["--only", "pins"])[0] == 0
    assert calls == [NOW, NOW]


def test_pins_runs_after_failure(monkeypatch, caplog):
    from pins import api as pins_api

    calls = []
    monkeypatch.setattr(pins_api, "purge_deleted_pins", lambda db, *, now: calls.append(now) or {})

    def fail(db, now):
        raise ValueError("private data")

    code, log = _run({"other": fail, "pins": run.purge_pins})
    assert code == 1 and calls == [NOW]
    assert log == ["rollback", "close", "commit", "close"]
    assert "ValueError" in caplog.text and "private data" not in caplog.text


# ---- 적체 측정과 되풀이(#1213) ----

def test_repeats_until_empty_and_reports_rounds(capsys, caplog):
    caplog.set_level("INFO", logger="maintenance")
    step = batched(25, 10)
    code, log = _run({"events": step})
    assert code == 0 and step.left == [0]
    assert log.count("commit") == 4          # 10 + 10 + 5 + 빈 확인
    out = capsys.readouterr().out
    assert "events: 25행, 4라운드" in out and "적체" not in out
    assert "적체=아니오" in caplog.text and "정리 마지막 성공" in caplog.text


def test_backlog_when_round_limit_hits(monkeypatch, capsys, caplog):
    monkeypatch.setattr(run, "MAX_ROUNDS", 3)
    step = batched(100, 10)
    code, _ = _run({"events": step})
    assert code == 0 and step.left == [70]   # 3라운드만 돌고 남겼다
    assert "적체: 더 남았을 수 있다" in capsys.readouterr().out
    warnings = [r for r in caplog.records if "정리 적체" in r.getMessage()]
    assert warnings and warnings[0].levelname == "WARNING"


def test_backlog_when_time_limit_hits(monkeypatch):
    ticks = iter([0, 400, 800])
    monkeypatch.setattr(run.time, "monotonic", lambda: next(ticks))
    result = run.run_step("events", batched(100, 10), lambda: FakeSession([]), now=NOW, dry_run=False)
    assert result.backlog and result.rounds == 1


def test_exact_multiple_of_limit_is_not_backlog(monkeypatch):
    monkeypatch.setattr(run, "MAX_ROUNDS", 3)
    result = run.run_step("events", batched(20, 10), lambda: FakeSession([]), now=NOW, dry_run=False)
    assert result.rounds == 3 and not result.backlog   # 10 + 10 + 빈 확인 — 라운드 상한 안에서 비었다


def test_personal_data_backlog_is_error(monkeypatch, caplog):
    monkeypatch.setattr(run, "MAX_ROUNDS", 2)
    _run({"withdrawn": batched(100, 10)})
    levels = {r.levelname for r in caplog.records if "정리 적체" in r.getMessage()}
    assert levels == {"ERROR"}


def test_backlog_log_has_counts_only(monkeypatch, caplog):
    monkeypatch.setattr(run, "MAX_ROUNDS", 2)
    caplog.set_level("INFO", logger="maintenance")
    _run({"withdrawn": batched(100, 10)})
    assert "user@example.com" not in caplog.text and "withdrawn" in caplog.text


def test_dry_run_calls_once_and_keeps_rollback(capsys):
    calls = []
    step = batched(100, 10, calls)
    code, log = _run({"events": step}, ["--dry-run"])
    assert code == 0 and len(calls) == 1
    assert "commit" not in log and log.count("rollback") == 1
    assert "events: 10행" in capsys.readouterr().out


def test_failure_in_later_round_keeps_earlier_commits_and_continues(capsys):
    n = []

    def flaky(db, now):
        n.append(1)
        if len(n) == 2:
            raise RuntimeError("x")
        return {"rows": 5}

    code, log = _run({"a": flaky, "b": once({"y": 1})})
    assert code == 1
    assert log == ["commit", "close", "rollback", "close", "commit", "close", "commit", "close"]
    assert "a: 실패" in capsys.readouterr().out


def test_last_success_not_logged_on_failure_or_dry_run(caplog):
    caplog.set_level("INFO", logger="maintenance")
    _run({"a": once({"x": 1})}, ["--dry-run"])
    assert "마지막 성공" not in caplog.text

    def boom(db, now):
        raise ValueError

    _run({"a": boom})
    assert "마지막 성공" not in caplog.text
