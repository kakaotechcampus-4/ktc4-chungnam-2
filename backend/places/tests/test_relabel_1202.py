import json
import tempfile
import time

from sqlalchemy import func, select

from places.models import PlaceFact
from places.scripts import relabel_cuisine_1093 as script
from places.tests.test_cuisine_names_1093 import _fact, _NoClose, _seed


def test_plan_out_contains_complete_original_rows(db_session, tmp_path):
    pid = _seed(db_session, "plan", "갓덴스시")
    path = tmp_path / "plan.jsonl"
    assert script.main(["--plan-out", str(path)], session_factory=lambda: _NoClose(db_session)) == 0
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows and all(set(row) == set(script.FACT_COLUMNS) for row in rows)
    row = next(row for row in rows if row["fact_key"] == "cuisine_chinese")
    assert row["place_id"] == str(pid) and row["value"] is False
    assert row["label_source"] == "license_business_type" and row["labeled_at"]
    assert script.main(["--plan-out", str(path)], session_factory=lambda: _NoClose(db_session)) == 1


def test_overlapping_apply_is_rejected(db_session, test_engine):
    with test_engine.connect() as other:
        assert other.scalar(select(func.pg_try_advisory_xact_lock(script.LOCK_ID)))
        assert script.main(["--apply"], session_factory=lambda: _NoClose(db_session)) == 1


def test_compare_and_swap_does_not_overwrite_changed_fact(db_session):
    pid = _seed(db_session, "cas", "갓덴스시")
    with tempfile.TemporaryFile("w+", encoding="utf-8") as spool:
        _, total, _, _ = script.plan_changes(db_session, spool, None, time.monotonic())
        fact = _fact(db_session, pid, "cuisine_chinese")
        fact.evidence = "new value"
        db_session.flush()
        assert script.apply_changes(db_session, spool, total, time.monotonic()) == total - 1
        db_session.expire_all()
        assert _fact(db_session, pid, "cuisine_chinese").evidence == "new value"


def test_count_mismatch_rolls_back_all_updates(db_session, monkeypatch):
    pid = _seed(db_session, "rollback", "갓덴스시")
    db_session.commit()
    original = script.apply_changes

    def mismatch(db, spool, total, started):
        assert original(db, spool, total, started) == total
        return total - 1

    monkeypatch.setattr(script, "apply_changes", mismatch)
    assert script.main(["--apply"], session_factory=lambda: _NoClose(db_session)) == 1
    db_session.expire_all()
    fact = _fact(db_session, pid, "cuisine_chinese")
    assert fact.value is False and fact.confidence == "known"
    assert db_session.scalar(select(func.count()).select_from(PlaceFact).where(PlaceFact.place_id == pid)) == 10


def test_apply_spans_multiple_batches(db_session, monkeypatch):
    """묶음이 여러 번 나가도 건수가 합쳐지고 적용 뒤 dry-run은 0건이다."""
    monkeypatch.setattr(script, "BATCH", 2)
    pid = _seed(db_session, "batches", "갓덴스시")
    db_session.commit()
    assert script.main(["--apply"], session_factory=lambda: _NoClose(db_session)) == 0
    db_session.expire_all()
    assert _fact(db_session, pid, "cuisine_chinese").confidence == "unknown"
    with tempfile.TemporaryFile("w+", encoding="utf-8") as spool:
        assert script.plan_changes(db_session, spool, None, time.monotonic())[1] == 0
