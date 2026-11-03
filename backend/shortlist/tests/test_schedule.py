from datetime import date
from types import SimpleNamespace

import pytest

from common.errors import AppError
from shortlist import core, service
from shortlist.schemas import ScheduleGroup


START = date(2026, 11, 12)
END = date(2026, 11, 15)


class FakeDB:
    def flush(self):
        pass


def row(id, day=None, order=None):
    return SimpleNamespace(id=id, scheduled_date=day, visit_order=order)


def test_replace_schedule_moves_between_days_and_rejects_stale(monkeypatch):
    rows = [row("one"), row("two")]
    monkeypatch.setattr(service, "lock_shortlist", lambda *_: None)
    monkeypatch.setattr(service, "list_items", lambda *_, **__: rows)
    version = service.schedule_version(START, END, rows)
    groups = [ScheduleGroup(date=START, item_ids=["two"]), ScheduleGroup(date=END, item_ids=["one"])]
    service.replace_schedule(FakeDB(), map_id="map", start_date=START, end_date=END, version=version, groups=groups)
    assert (rows[0].scheduled_date, rows[1].scheduled_date) == (END, START)
    with pytest.raises(AppError) as exc:
        service.replace_schedule(FakeDB(), map_id="map", start_date=START, end_date=END, version=version, groups=groups)
    assert exc.value.code == "SHORTLIST_STALE"


def test_schedule_rejects_duplicates_and_outside_dates(monkeypatch):
    rows = [row("one")]
    monkeypatch.setattr(service, "lock_shortlist", lambda *_: None)
    monkeypatch.setattr(service, "list_items", lambda *_, **__: rows)
    version = service.schedule_version(START, END, rows)
    for groups in ([ScheduleGroup(date=START, item_ids=["one", "one"])],
                   [ScheduleGroup(date=date(2026, 11, 16), item_ids=["one"])],
                   [ScheduleGroup(date=START, item_ids=[])]):
        with pytest.raises(AppError) as exc:
            service.replace_schedule(FakeDB(), map_id="map", start_date=START, end_date=END, version=version, groups=groups)
        assert exc.value.code == "VALIDATION_ERROR"


def test_shortened_trip_preserves_places_in_unassigned(monkeypatch):
    rows = [row("a", START, 0), row("b", END, 0), row("c", None, 0)]
    monkeypatch.setattr(service, "lock_shortlist", lambda *_: None)
    monkeypatch.setattr(service, "list_items", lambda *_, **__: rows)
    assert service.unassign_outside_dates(FakeDB(), map_id="map", start_date=START, end_date=START) == 1
    assert rows[1].scheduled_date is None and rows[1].visit_order == 1
    assert rows[2].visit_order == 0


def test_export_includes_dates_and_unassigned():
    rows = [core.ExportRow(1, "A", "카페", "", "", "2026-11-12"),
            core.ExportRow(1, "B", "카페", "", "")]
    assert "[2026-11-12]" in core.render_txt(rows)
    assert "[미배정]" in core.render_txt(rows)
    assert "날짜,순서" in core.render_csv(rows)
    assert "미배정,1,B" in core.render_csv(rows)


def test_export_with_only_unassigned_shows_heading():
    assert core.render_txt([core.ExportRow(1, "A", "카페", "", "")]).startswith("[미배정]\n")
