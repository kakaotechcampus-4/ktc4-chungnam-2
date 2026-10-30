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


def _run(steps, argv=(), log=None):
    log = [] if log is None else log
    code = run.main(list(argv), session_factory=lambda: FakeSession(log), now=NOW, steps=steps)
    return code, log


def test_each_step_commits_and_reports(capsys):
    steps = {"a": lambda db, now: {"x": 2}, "b": lambda db, now: {"y": 1, "z": 3}}
    code, log = _run(steps)
    assert code == 0
    assert log == ["commit", "close", "commit", "close"]
    out = capsys.readouterr().out
    assert "a: 2행" in out and "b: 4행" in out


def test_failed_step_does_not_block_others(capsys, caplog):
    def boom(db, now):
        raise ValueError("user@example.com")

    steps = {"a": boom, "b": lambda db, now: {"y": 1}}
    code, log = _run(steps)
    assert code == 1
    assert log == ["rollback", "close", "commit", "close"]
    out = capsys.readouterr().out
    assert "a: 실패" in out and "b: 1행" in out
    assert "ValueError" in caplog.text and "user@example.com" not in caplog.text


def test_dry_run_rolls_back_every_step(capsys):
    steps = {"a": lambda db, now: {"x": 2}, "b": lambda db, now: {"y": 1}}
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


def test_default_steps_are_the_four_stages():
    assert list(run.STEPS) == ["maps", "notifications", "guests", "llm_calls"]


def test_format_report_shows_map_count_apart_from_rows():
    out = run.format_report({"maps": {"deleted_maps": 2, "pins": 5, "maps": 2}}, dry_run=False)
    assert "maps: 7행 (지도 2개)" in out
