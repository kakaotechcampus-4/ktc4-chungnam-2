"""관리 스크립트(docs/ads.md 8절, 11절 16번) — 등록은 전부 통과해야 넣고 하나라도 틀리면 아무것도 넣지 않는다."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy import select

from ads.models import Ad
from ads.scripts import deactivate, register
from ads.tests.conftest import NOW
from places.models import Place

HEADER = "place_id,starts_at,ends_at,memo\n"


def csv_line(place_id, start="2026-11-01T00:00:00+09:00", end="2026-12-01T00:00:00+09:00", memo="광고주 A"):
    return f"{place_id},{start},{end},{memo}\n"


def ads_in(db) -> list[Ad]:
    return list(db.execute(select(Ad)).scalars())


# ---------------------------------------------------------------- CSV 읽기

def test_parse_csv_reads_rows_and_treats_naive_times_as_seoul():
    pid = str(uuid.uuid4())
    drafts, errors = register.parse_csv("﻿" + HEADER + csv_line(pid, start="2026-11-01T00:00:00", memo=""))

    assert errors == []
    [d] = drafts
    assert (d.line, d.place_id, d.memo) == (2, pid, None)
    assert d.starts_at == datetime(2026, 10, 31, 15, 0, tzinfo=timezone.utc)


def test_parse_csv_reports_format_errors_by_line():
    _, errors = register.parse_csv(HEADER + csv_line("nope") + csv_line(str(uuid.uuid4()), start="어제"))

    assert errors == ["2줄: place_id 형식이 틀렸다('nope')", "3줄: starts_at, ends_at은 ISO 8601 시각이어야 한다"]
    assert register.parse_csv("id,from,to\n")[1][0].startswith("머리글이")
    assert register.parse_csv(HEADER)[1] == ["등록할 행이 없다"]


# ---------------------------------------------------------------- 검증과 전부 아니면 전무

def test_register_inserts_every_row_when_all_are_valid(world):
    a, b = world.place("카페 A"), world.place("식당 B", category="음식점")
    drafts, _ = register.parse_csv(HEADER + csv_line(a) + csv_line(b, memo=""))

    ad_ids = register.register(world.db, drafts, now=NOW)

    rows = {str(r.id): r for r in ads_in(world.db)}
    assert set(ad_ids) <= set(rows)
    assert {(rows[i].place_id, rows[i].active, rows[i].memo) for i in ad_ids} == {(a, True, "광고주 A"), (b, True, None)}


def test_one_bad_row_inserts_nothing(world):
    good = world.place("좋은 카페")
    closed = world.place("폐업 카페", status="closed")
    taken = world.place("광고 중인 카페")
    world.ad(taken)
    missing = str(uuid.uuid4())
    before = len(ads_in(world.db))
    text = HEADER + "".join([
        csv_line(good),
        csv_line(closed),
        csv_line(missing),
        csv_line(taken),
        csv_line(good),                                                                   # CSV 안 중복
        csv_line(world.place("거꾸로 카페"), start="2026-12-01T00:00:00+09:00", end="2026-11-01T00:00:00+09:00"),
        csv_line(world.place("끝난 카페"), start="2026-10-01T00:00:00+09:00", end="2026-10-02T00:00:00+09:00"),
    ])
    drafts, _ = register.parse_csv(text)

    with pytest.raises(register.RegisterError) as exc:
        register.register(world.db, drafts, now=NOW)

    errors = "\n".join(exc.value.errors)
    assert "3줄: status가 open이 아니거나" in errors
    assert f"4줄: places에 없는 장소다({missing})" in errors
    assert "5줄: 이 장소에 active 광고가 이미 있다" in errors
    assert "6줄: 같은 장소가 2줄에 이미 있다" in errors
    assert "7줄: starts_at이 ends_at보다 앞이어야 한다" in errors
    assert "8줄: ends_at이 이미 지났다" in errors
    assert not any(e.startswith("2줄") for e in exc.value.errors)   # 좋은 행 자체에는 오류가 없다
    assert len(ads_in(world.db)) == before


def test_registering_does_not_touch_places(world):
    """16번 — 광고를 등록해도 places.curated가 바뀌지 않고 places 행이 늘지 않는다."""
    off, on = world.place("추천 불가", curated=False), world.place("추천 가능", curated=True)
    count = world.db.execute(select(sa.func.count()).select_from(Place)).scalar_one()

    register.register(world.db, register.parse_csv(HEADER + csv_line(off) + csv_line(on))[0], now=NOW)

    flags = dict(world.db.execute(select(Place.id, Place.curated).where(Place.id.in_([off, on]))).all())
    assert flags == {uuid.UUID(off): False, uuid.UUID(on): True}
    assert world.db.execute(select(sa.func.count()).select_from(Place)).scalar_one() == count


def test_main_commits_all_or_nothing(factory, monkeypatch, tmp_path, capsys):
    """main은 자기 세션으로 커밋한다 — 테스트 DB에 붙여 실제 커밋 경로를 본다. 끝나면 factory가 ads를 비운다(#594)."""
    import common.database

    monkeypatch.setattr(common.database, "SessionLocal", factory)
    with factory() as db:
        place = Place(source="permit", source_id=f"ads-main-{uuid.uuid4().hex[:8]}", name="커밋 카페", category="카페",
                      geom="SRID=4326;POINT(127.0561 37.5445)", status="open")
        db.add(place)
        db.commit()
        place_id = str(place.id)
    end = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    try:
        bad = tmp_path / "bad.csv"
        bad.write_text(HEADER + csv_line(place_id, end=end) + csv_line(str(uuid.uuid4()), end=end), encoding="utf-8")
        assert register.main(["--csv", str(bad)]) == 1
        assert "아무것도 넣지 않았다" in capsys.readouterr().err
        with factory() as db:
            assert ads_in(db) == []

        good = tmp_path / "good.csv"
        good.write_text(HEADER + csv_line(place_id, end=end), encoding="utf-8")
        assert register.main(["--csv", str(good), "--dry-run"]) == 0
        with factory() as db:
            assert ads_in(db) == []
        assert register.main(["--csv", str(good)]) == 0
        with factory() as db:
            [row] = ads_in(db)
        assert row.place_id == place_id

        assert deactivate.main([str(row.id)]) == 0
        assert deactivate.main([str(row.id)]) == 0
        assert deactivate.main([str(uuid.uuid4())]) == 1
        with factory() as db:
            assert db.get(Ad, row.id).active is False
    finally:
        with factory() as db:
            db.execute(sa.delete(Ad))
            db.execute(sa.delete(Place).where(Place.id == uuid.UUID(place_id)))
            db.commit()


# ---------------------------------------------------------------- 내리기

def test_deactivate_turns_active_off_once(world):
    ad_id = world.ad(world.place("카페"))

    assert deactivate.deactivate(world.db, ad_id) is True
    assert deactivate.deactivate(world.db, ad_id) is False
    assert deactivate.deactivate(world.db, str(uuid.uuid4())) is None
    assert deactivate.deactivate(world.db, "nope") is None
    assert world.db.get(Ad, uuid.UUID(ad_id)).active is False


def test_partial_unique_allows_a_new_ad_after_deactivating(world):
    place = world.place("카페")
    first = world.ad(place)
    with pytest.raises(sa.exc.IntegrityError), world.db.begin_nested():
        world.ad(place)
    deactivate.deactivate(world.db, first)

    world.ad(place)   # 내린 뒤에는 같은 장소에 새 active 광고를 걸 수 있다


def test_period_check_constraint(world):
    with pytest.raises(sa.exc.IntegrityError), world.db.begin_nested():
        world.ad(world.place("카페"), starts_at=NOW, ends_at=NOW)
