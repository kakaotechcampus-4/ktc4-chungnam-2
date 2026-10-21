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


# ---- 요청 목표 비교(pivot 4절) ----

class _FakeSetter:
    """목표 세우기 모델 자리 대역: 정답 그대로 돌려준다."""
    calls, failures, tokens = 1, [], (10, 2)

    def __init__(self, goal_set):
        self._goal_set = goal_set

    def __call__(self, _input):
        return self._goal_set


class _FakeDecider:
    calls, failures, tokens = 2, [], (30, 4)

    def __init__(self):
        self._queue = []

    def __call__(self, turn_input):
        from llm.schemas import CourseDirectTurn
        tool = {"action": {"tool": "optimize", "priority": [g["id"] for g in turn_input["goals"]], "locks": []}} if not turn_input["candidates"] \
            else {"action": {"tool": "finish", "candidate_id": "c1"}}
        return CourseDirectTurn.model_validate({"thought": "해 볼게요", **tool})


def _request(m, kind="night"):
    return {"map_id": m["id"], "kind": kind, "request_text": "첫날 저녁엔 야경 보면서 마무리하고 싶어요",
            "gold_goals": [{"kind": "night_end", "day": "d1", "places": []}], "gold_unmatched": []}


def test_요청_비교는_정답_주입이_기준선보다_요청을_더_지킨다():
    maps = build_maps.build_all(fake_records(), 4)
    results = [compare.run_request_variants(compare.scenario_from_map(m), _request(m)) for m in maps]
    assert all(set(r) == {"draft", "strong", "strong_gold"} for r in results)
    table = compare.aggregate_requests(results)
    assert table["strong_gold"]["goal_met"] >= table["strong"]["goal_met"]
    assert table["strong_gold"]["hard_confirmed"] <= table["draft"]["hard_confirmed"]
    assert "goal_met" in compare.format_table(table, len(maps))


def test_요청_비교의_에이전트는_목표_세우기_정확도와_모델_사용량을_잰다():
    from llm.schemas import CourseGoalSet
    m = build_maps.build_all(fake_records(), 1)[0]
    req = _request(m)
    right = CourseGoalSet.model_validate({"goals": [{"kind": "night_end", "day": "d1", "places": [], "source": "request",
                                                      "quote": "첫날 저녁엔 야경", "reaction_ids": []}], "unmatched": []})
    out = compare.run_request_variants(compare.scenario_from_map(m), req, goal_setter=_FakeSetter(right), decider=_FakeDecider())
    agent = out["agent"]
    assert agent.goals_exact is True and agent.goals_trap_ok is None and agent.calls == 3
    assert (agent.tokens_in, agent.tokens_out) == (40, 6)
    assert agent.gold_met == out["strong_gold"].gold_met

    wrong = CourseGoalSet.model_validate({"goals": [], "unmatched": []})
    trap = {**req, "gold_goals": [], "gold_unmatched": [req["request_text"]]}
    out = compare.run_request_variants(compare.scenario_from_map(m), trap, goal_setter=_FakeSetter(wrong), decider=_FakeDecider())
    assert out["agent"].goals_exact is True and out["agent"].goals_trap_ok is True      # 함정에서 목표 0개


def test_요청_비교는_목표_세우기_실패를_목표_없이_진행한다():
    from agent.course.deps import ModelTurnFailed
    from llm.api import AgentCallFailed
    m = build_maps.build_all(fake_records(), 1)[0]

    def failing(_input):
        raise ModelTurnFailed(AgentCallFailed(reason="timeout", detail="x"))
    failing.calls, failing.failures, failing.tokens = 1, [object()], (0, 0)
    out = compare.run_request_variants(compare.scenario_from_map(m), _request(m), goal_setter=failing, decider=_FakeDecider())
    assert out["agent"].goals_exact is False and out["agent"].failures == 1


def test_요청_비교는_작업_기록을_단계_모양으로_담는다():
    from llm.schemas import CourseGoalSet
    m = build_maps.build_all(fake_records(), 1)[0]
    req = _request(m)
    right = CourseGoalSet.model_validate({"goals": [{"kind": "night_end", "day": "d1", "places": [], "source": "request",
                                                      "quote": "첫날 저녁엔 야경", "reaction_ids": []}], "unmatched": []})
    out = compare.run_request_variants(compare.scenario_from_map(m), req, goal_setter=_FakeSetter(right), decider=_FakeDecider())
    log = out["agent"].worklog
    assert log[0].startswith("[이해] 해석(모델)") and any(l.startswith("[확인] 검증(코드)") for l in log) and log[-1].startswith("[결과]")
    assert out["strong_gold"].worklog[0].startswith("[이해] 해석(정답 주입)") and out["strong"].worklog == ()


def test_시연은_요청_문장을_직접_받아_작업_기록을_찍는다(tmp_path):
    from agent.course.eval import demo
    data = tmp_path / "data"
    (data / "maps").mkdir(parents=True)
    (data / "maps" / "map_00.json").write_text(json.dumps(build_maps.build_all(fake_records(), 1)[0]), encoding="utf-8")
    lines: list[str] = []
    demo.run_direct_demo(0, data, use_model=False, request="첫날 저녁엔 야경 보고 싶어요", out=lines.append)
    text = "\n".join(lines)
    assert "요청: 첫날 저녁엔 야경 보고 싶어요" in text and "[이해] 해석(스텁)" in text and "「첫날 저녁엔 야경 보고 싶어요」는 그대로는 판단할 수 없어요" in text
    assert "▶ 최종 코스" in text
