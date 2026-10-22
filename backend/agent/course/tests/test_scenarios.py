"""시연 시나리오 — 쉬는 날에 걸린 목표를 코드가 먼저 찾아 묻는 흐름(choose_day). 기대 흐름은 생성 스크립트가 원자료에서 따로 계산한다."""

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


def test_기대_흐름이_스텁_모델_없이_그대로_나온다(built):
    maps, scenarios = built
    for s in scenarios:
        sc, gold, result = run(maps[s["map_id"]], s)
        exp = s["expected"]
        first_check = result.steps[0].result.data["checks"][0]
        assert first_check["reasons"] == exp["reasons"] and first_check["feasible"] is False
        q = result.questions[0]
        assert (q.kind, q.subject, q.default) == (exp["question"], exp["subject"], exp["default"])
        assert q.options[-1] == direct.DROP and q.option_labels[-1] == "그 목표는 빼기" and exp["default"] in q.options
        assert exp["goal_after"] in {g.id for g in result.state.goals}                       # 답(기본값)으로 목표가 고쳐졌다
        assert exp["subject"] not in {g.id for g in result.state.goals}
        ask = next(step for step in result.steps if step.call.get("tool") == "ask_requester")
        assert ask.by == "code" and ask.substituted_for["error"] == "QUESTION_OPENED_BY_CODE"
        assert "기본값" in q.default_reason and "코드가 고른 첫 여는 날" in q.default_reason


def test_답한_뒤_다시_확인하고_다시_짠다(built):
    maps, scenarios = built
    s = scenarios[0]
    sc, gold, result = run(maps[s["map_id"]], s)
    tools = [step.call["tool"] for step in result.steps]
    assert tools[:3] == ["check_goals", "ask_requester", "check_goals"] and "optimize" in tools[3:]
    after = result.steps[2].result.data["checks"][0]
    assert after["id"] == s["expected"]["goal_after"] and after["feasible"] is True
    # 장소를 빼지 않는다: 코스에 모든 장소가 그대로 있다
    assert sorted(p for day in result.course for p in day) == sorted(p.alias for p in sc.trip.places)
    # 고친 목표는 코드가 새 날짜로 지켜 준다
    new_goal = next(g for g in result.state.goals if g.id == s["expected"]["goal_after"])
    assert G.evaluate(sc.trip, result.course, new_goal).met is True


def test_작업_기록은_확인_질문_답_다시짜기_순서로_이어진다(built):
    maps, scenarios = built
    s = scenarios[0]
    sc, gold, result = run(maps[s["map_id"]], s)
    lines = worklog.render(sc.trip, gold, [], result, understood_by="스텁")
    stages = [l.split("]")[0][1:] for l in lines]
    order = [stages.index("확인"), stages.index("질문"), stages.index("답"), stages.index("다시 짜기")]
    assert order == sorted(order) and "확인" in stages[stages.index("답"):]
    ask = next(l for l in lines if l.startswith("[질문]"))
    assert "코드가 열음" in ask and "로 옮길까요?" in ask and "그 목표는 빼기" in ask and "기본값" in ask and "코드가 고른 첫 여는 날" in ask
    assert "이어 가요" in next(l for l in lines if l.startswith("[답]"))


def test_야경_시나리오는_야경_질문_문구를_쓴다(built):
    maps, scenarios = built
    s = next(x for x in scenarios if x["kind"] == "closed_night")
    sc, gold, result = run(maps[s["map_id"]], s)
    q = result.questions[0]
    assert "야경 장소" in q.text and "쉬어요" in q.text and q.text.endswith("마지막으로 할까요?")


def test_모델이_제안한_날이_기본값이_되고_다른_행동은_코드가_먼저_묻는다(built):
    maps, scenarios = built
    s = next(x for x in scenarios if x["kind"] == "closed_place" and len(maps[x["map_id"]]["days"]) == 3)
    sc = compare.scenario_from_map(maps[s["map_id"]])
    gold = compare.gold_goals(sc, s)
    # 모델은 여는 날 중 마지막 날을 첫 선택지로 제안한다
    st = initial_state(sc.trip, sc.start_hours, core.draft_course(sc.trip), gold)
    pend = direct.pending_closure(direct.DirectState(st, checks=G.check_goals(sc.trip, sc.start_hours, gold)))
    proposal = list(reversed(pend["days"]))
    decide = scripted({"tool": "ask_requester", "kind": "choose_day", "subject": pend["goal"].id, "options": proposal},
                      {"tool": "optimize", "priority": [], "locks": []}, {"tool": "finish", "candidate_id": "c1"})
    result = direct.run_direct(st, decide=decide, hours=sc.gateway)
    assert result.questions[0].default == proposal[0] and decide.seen[0]["must_ask"]["kind"] == "choose_day"
    assert decide.seen[0]["must_ask"]["options"] == pend["days"] and "모델이 제안" in result.questions[0].default_reason
    assert result.steps[1].by == "model"

    # 모델이 질문 대신 optimize를 골라도 코드가 먼저 묻는다
    decide = scripted({"tool": "optimize", "priority": [], "locks": []}, {"tool": "optimize", "priority": [], "locks": []},
                      {"tool": "finish", "candidate_id": "c1"})
    result = direct.run_direct(st, decide=decide, hours=sc.gateway)
    ask = next(step for step in result.steps if step.call.get("tool") == "ask_requester")
    assert ask.by == "code" and ask.substituted_for["call"]["tool"] == "optimize" and result.questions[0].default == pend["days"][0]

    # 모델이 쉬는 날을 선택지에 넣으면 거절하고 코드가 대신 연다
    closed = pend["goal"].day
    decide = scripted({"tool": "ask_requester", "kind": "choose_day", "subject": pend["goal"].id, "options": [closed]},
                      {"tool": "optimize", "priority": [], "locks": []}, {"tool": "finish", "candidate_id": "c1"})
    result = direct.run_direct(st, decide=decide, hours=sc.gateway)
    ask = next(step for step in result.steps if step.call.get("tool") == "ask_requester")
    assert ask.by == "code" and ask.substituted_for["error"] == "INVALID_MOVE" and result.questions[0].default == pend["days"][0]


def test_옮길_여는_날이_없으면_묻지_않고_목표를_빼지도_않는다(built):
    maps, scenarios = built
    s = scenarios[0]
    m = copy.deepcopy(maps[s["map_id"]])
    pid = s["gold_goals"][0]["places"][0]
    place = next(p for p in m["places"] if p["alias"] == pid)
    place["hours"] = {wd: "closed" for wd in place["hours"]}               # 어느 날도 안 연다
    sc, gold, result = run(m, s)
    assert len(result.questions) == 0
    assert gold[0].id in {g.id for g in result.state.goals}                  # 목표를 코드가 대신 빼지 않는다
    assert result.steps[0].result.data["checks"][0]["reasons"] == [G.PLACE_CLOSED_ON_DAY]


def test_질문_상한은_둘이고_넘는_쉬는_날_목표는_묻지_않는다(built):
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
    assert [q.kind for q in result.questions] == ["choose_day", "choose_day"]
    assert sum(not G.check_goal(sc.trip, result.state.hours, g)["feasible"] for g in result.state.goals) == 1   # 셋째는 묻지 못하고 확인 줄로만 남는다


def test_요청_세트와_숫자는_섞이지_않는다(built):
    _, scenarios = built
    assert all(s.get("scenario") for s in scenarios)               # 평가 집계(aggregate_requests)는 requests.json만 읽는다
    assert "scenarios" not in open(compare.__file__, encoding="utf-8").read().split("def _main_requests")[1].split("def main")[0]
