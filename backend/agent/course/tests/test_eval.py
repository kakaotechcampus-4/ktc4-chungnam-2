"""평가 도구 시험 — 실제 데이터 없이 가짜 장소로 지도 생성과 비교 실행기가 도는지만 본다."""

import json
import random
from datetime import date

from agent.course.eval import build_maps, compare
from agent.course.eval.build_maps import Record

CLOSED_MON = {wd: ("closed" if wd == 0 else "open") for wd in range(7)}
CLOSED_SUN = {wd: ("closed" if wd == 6 else "open") for wd in range(7)}
OPEN = {wd: "open" for wd in range(7)}
UNKNOWN = {wd: "unknown" for wd in range(7)}


def fake_records() -> list[Record]:
    rng = random.Random(1)
    out = []
    for gu in ("가구", "나구"):
        for i in range(10):
            hours = [CLOSED_MON, CLOSED_SUN, OPEN, UNKNOWN][i % 4]
            out.append(Record(f"tour:{gu}{i}", f"{gu}관광{i}", gu, "관광지", 37.5 + rng.random() / 50, 127 + rng.random() / 50,
                              ("night_view",) if i == 2 else (), dict(hours)))
        for i in range(6):
            out.append(Record(f"음식점:{gu}{i}", f"{gu}식당{i}", gu, "음식점", 37.5 + rng.random() / 50, 127 + rng.random() / 50, (), dict(OPEN)))
            out.append(Record(f"카페:{gu}{i}", f"{gu}카페{i}", gu, "카페", 37.5 + rng.random() / 50, 127 + rng.random() / 50, (), dict(OPEN)))
    return out


def test_같은_시드는_같은_지도():
    a = build_maps.build_all(fake_records(), 4, seed=7)
    assert a == build_maps.build_all(fake_records(), 4, seed=7)
    assert len(a) == 4
    assert a != build_maps.build_all(fake_records(), 4, seed=8)


def test_지도는_휴무_함정과_필요한_구성을_갖는다():
    for m in build_maps.build_all(fake_records(), 4):
        assert 8 <= len(m["places"]) <= 14
        assert len({p["alias"] for p in m["places"]}) == len(m["places"])
        closed_on_trip = [
            p for p in m["places"]
            if any(p["hours"][str(date.fromisoformat(d).weekday())] == "closed" for d in m["days"])
        ]
        assert len(closed_on_trip) >= 2          # 여행 기간에 쉬는 곳이 일부러 들어 있다


def test_요약에는_장소_이름이_없다():
    summary = build_maps.summarize(build_maps.build_all(fake_records(), 4))
    text = json.dumps(summary, ensure_ascii=False)
    assert not any(r.name in text for r in fake_records()) and "가구" not in text and "나구" not in text
    assert summary["maps"] == 4


def test_비교_실행기는_세_변형을_진짜_영업시간으로_채점한다():
    maps = build_maps.build_all(fake_records(), 4)
    results = [compare.run_variants(compare.scenario_from_map(m)) for m in maps]
    assert all(set(r) == {"draft", "baseline", "strong"} for r in results)
    table = compare.aggregate(results)
    # 기준선은 조회로 휴무를 알아내 초안보다 확정 위반이 늘지 않는다
    assert table["baseline"]["hard_confirmed"] <= table["draft"]["hard_confirmed"]
    assert "baseline" in compare.format_table(table, len(maps))


def test_모델_변형은_decide가_있을_때만_돈다():
    from agent.course.schemas import AgentTurn, Finish
    m = build_maps.build_all(fake_records(), 1)[0]
    decide = lambda _input: AgentTurn(thought="마칩니다", plan=[], lesson=None, action=Finish(tool="finish", reason_code="no_progress"))
    out = compare.run_variants(compare.scenario_from_map(m), decide)
    assert set(out) == {"draft", "baseline", "strong", "agent"}


def test_시작_스냅샷은_데이터에_휴무가_있는_곳만_안다():
    for m in build_maps.build_all(fake_records(), 4):
        for p in m["places"]:
            has_data = any(s != "unknown" for s in p["hours"].values())
            assert p["known_at_start"] == has_data


def test_비교_기본은_확인필요_모드():
    m = build_maps.build_all(fake_records(), 1)[0]
    assert compare.scenario_from_map(m).trip.unknown_hours == "check"
