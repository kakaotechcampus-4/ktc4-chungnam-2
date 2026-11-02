"""시연 시나리오 — 쉬는 날에 걸린 목표를 코드가 찾아 묻지 않고 푸는 흐름(#1131, 예전 choose_day 질문). 기대 흐름은 생성 스크립트가 원자료에서 따로 계산한다."""

import copy
from datetime import date

import pytest

from agent.course import core, direct, goals as G, worklog
from agent.course.eval import build_maps, build_scenarios, compare
from agent.course.state import initial_state
from agent.course.tests.test_eval import fake_records
from llm.schemas import CourseDirectTurn


def turn(**action):
    return CourseDirectTurn.model_validate({"thought": "해 볼게요", "action": action})


def scripted(*actions):
    queue = [turn(**a) for a in actions]
    seen = []

    def decide(turn_input):
        seen.append(turn_input)
        return queue.pop(0)

    decide.seen = seen
    return decide


def maps_with_night():
    maps = build_maps.build_all(fake_records(), 4)
    m = copy.deepcopy(maps[1])
    night = next(p for p in m["places"] if "night_view" in p["labels"])
    first = str(date.fromisoformat(m["days"][0]).weekday())
    night["hours"] = {str(wd): ("closed" if str(wd) == first else "open") for wd in range(7)}
    night["known_at_start"] = True
    for other in m["places"]:                       # 이 지도에서는 야경 장소가 하나뿐이어야 "모두 쉼"이 된다
        if other is not night and "night_view" in other["labels"]:
            other["labels"] = [x for x in other["labels"] if x != "night_view"]
    m["id"] = "map_night"
    return [*maps, m]


def run(m, req, decide=None):
    sc = compare.scenario_from_map(m)
    gold = compare.gold_goals(sc, req)
    st = initial_state(sc.trip, sc.start_hours, core.draft_course(sc.trip), gold)
    return sc, gold, direct.run_direct(st, decide=decide, hours=sc.gateway)


@pytest.fixture(scope="module")
def built():
    maps = maps_with_night()
    return {m["id"]: m for m in maps}, build_scenarios.build_scenarios(maps)


def test_시나리오는_5개_안팎이고_평가_세트_표시가_다르다(built):
    _, scenarios = built
    assert {s["kind"] for s in scenarios} >= {"closed_place", "closed_night"}
    assert all(s["scenario"] is True and s["gold_unmatched"] == [] for s in scenarios)
    assert len({s["map_id"] for s in scenarios}) == len(scenarios)            # 지도마다 하나


def _resolved(result):
    return next(step for step in result.steps if step.call.get("tool") == direct.RESOLVE_CLOSURE)


def test_기대_흐름이_스텁_모델_없이_그대로_나온다(built):
    """묻지 않는다(#1131): 코드가 여는 날마다 옮겨 짜 보고 가장 나은 날로 목표를 고친다. 기대 흐름의 기본값은 여는 날 중 하나일 뿐이다."""
    maps, scenarios = built
    for s in scenarios:
        sc, gold, result = run(maps[s["map_id"]], s)
        exp = s["expected"]
        first_check = result.steps[0].result.data["checks"][0]
        assert first_check["reasons"] == exp["reasons"] and first_check["feasible"] is False
        step = _resolved(result)
        data = step.result.data
        assert step.by == "code" and data["goal_before"] == exp["subject"]
        assert exp["default"] in [t["day"] for t in data["tried"]] and data["chosen_day"] in [t["day"] for t in data["tried"]]
        assert data["goal_after"] in {g.id for g in result.state.goals} and exp["subject"] not in {g.id for g in result.state.goals}
        assert G.retarget(next(g for g in gold if g.id == exp["subject"]), data["chosen_day"]).id == data["goal_after"]


def test_고친_뒤_다시_확인하고_모델_없이_끝낸다(built):
    maps, scenarios = built
    s = scenarios[0]
    sc, gold, result = run(maps[s["map_id"]], s)
    tools = [step.call["tool"] for step in result.steps]
    assert tools == ["check_goals", direct.RESOLVE_CLOSURE, "check_goals", "finish"]
    after = result.steps[2].result.data["checks"][0]
    assert after["id"] == _resolved(result).result.data["goal_after"] and after["feasible"] is True
    # 장소를 빼지 않는다: 코스에 모든 장소가 그대로 있다
    assert sorted(p for day in result.course for p in day) == sorted(p.alias for p in sc.trip.places)
    new_goal = next(g for g in result.state.goals if g.id == _resolved(result).result.data["goal_after"])
    assert G.evaluate(sc.trip, result.course, new_goal).met is True


def test_고른_날은_옮겨_본_날_중_가장_낫다(built):
    maps, scenarios = built
    for s in scenarios:
        _, _, result = run(maps[s["map_id"]], s)
        tried = _resolved(result).result.data["tried"]
        chosen = next(t for t in tried if t["day"] == _resolved(result).result.data["chosen_day"])
        assert all((chosen["confirmed"], -chosen["kept"]) <= (t["confirmed"], -t["kept"]) for t in tried)


def test_작업_기록은_찾기_옮겨보기_비교_결정_순서이고_질문이_없다(built):
    maps, scenarios = built
    s = scenarios[0]
    sc, gold, result = run(maps[s["map_id"]], s)
    lines = worklog.render(sc.trip, gold, [], result, understood_by="스텁")
    stages = [l.split("]")[0][1:] for l in lines]
    assert "질문" not in stages and "답" not in stages
    order = [stages.index("확인"), stages.index("찾기"), stages.index("옮겨 보기"), stages.index("비교"), stages.index("결정")]
    assert order == sorted(order) and "확인" in stages[stages.index("결정"):]
    assert stages.count("옮겨 보기") == len(_resolved(result).result.data["tried"])
    decided = next(l for l in lines if l.startswith("[결정]"))
    assert "쉬어요. 그래서 이 목표를" in decided and "{" not in decided and "결정(코드)" in decided


def test_야경_시나리오는_야경_결정_문구를_쓴다(built):
    maps, scenarios = built
    s = next(x for x in scenarios if x["kind"] == "closed_night")
    _, _, result = run(maps[s["map_id"]], s)
    assert "야경 장소가 모두 쉬어요. 그래서 야경 목표를" in _resolved(result).note and _resolved(result).guard == ()


def test_모델이_있어도_코드가_먼저_풀고_모델_턴을_쓰지_않는다(built):
    maps, scenarios = built
    s = next(x for x in scenarios if x["kind"] == "closed_place")
    sc = compare.scenario_from_map(maps[s["map_id"]])
    gold = compare.gold_goals(sc, s)
    st = initial_state(sc.trip, sc.start_hours, core.draft_course(sc.trip), gold)
    decide = scripted({"tool": "finish", "candidate_id": "c1"})
    result = direct.run_direct(st, decide=decide, hours=sc.gateway)
    assert result.model_turns == 1 and decide.seen[0]["last_result"]["tool"] == "check_goals"
    assert decide.seen[0]["candidates"] and "must_ask" not in decide.seen[0] and "asked" not in decide.seen[0]
    assert {g.id for g in result.state.goals} == {g.id for g in st.goals} - {s["expected"]["subject"]} | {_resolved(result).result.data["goal_after"]}


def test_옮길_여는_날이_없으면_풀지_않고_목표를_빼지도_않는다(built):
    maps, scenarios = built
    s = scenarios[0]
    m = copy.deepcopy(maps[s["map_id"]])
    pid = s["gold_goals"][0]["places"][0]
    place = next(p for p in m["places"] if p["alias"] == pid)
    place["hours"] = {wd: "closed" for wd in place["hours"]}               # 어느 날도 안 연다
    sc, gold, result = run(m, s)
    assert not any(step.call.get("tool") == direct.RESOLVE_CLOSURE for step in result.steps)
    assert gold[0].id in {g.id for g in result.state.goals}                  # 목표를 코드가 대신 빼지 않는다
    assert result.steps[0].result.data["checks"][0]["reasons"] == [G.PLACE_CLOSED_ON_DAY]


def test_쉬는_날_목표가_여럿이면_하나씩_모두_푼다(built):
    maps, scenarios = built
    m = copy.deepcopy(maps[scenarios[0]["map_id"]])
    first = str(date.fromisoformat(m["days"][0]).weekday())
    tours = [p for p in m["places"] if p["category"] == "관광지"][:3]
    assert len(tours) == 3
    for p in tours:                                              # 세 곳 모두 첫날만 쉬고 시작 때 안다
        p["hours"] = {str(wd): ("closed" if str(wd) == first else "open") for wd in range(7)}
        p["known_at_start"] = True
    sc = compare.scenario_from_map(m)
    goals = tuple(G.normalize(sc.trip, "place_on_day", "d1", [p["alias"]])[0] for p in tours)
    st = initial_state(sc.trip, sc.start_hours, core.draft_course(sc.trip), goals)
    result = direct.run_direct(st, decide=None, hours=sc.gateway)
    assert sum(step.call.get("tool") == direct.RESOLVE_CLOSURE for step in result.steps) == 3       # 질문 상한(둘)이 없어졌다
    assert all(G.check_goal(sc.trip, result.state.hours, g)["feasible"] is not False for g in result.state.goals)


def test_요청_세트와_숫자는_섞이지_않는다(built):
    _, scenarios = built
    assert all(s.get("scenario") for s in scenarios)               # 평가 집계(aggregate_requests)는 requests.json만 읽는다
    assert "scenarios" not in open(compare.__file__, encoding="utf-8").read().split("def _main_requests")[1].split("def main")[0]
