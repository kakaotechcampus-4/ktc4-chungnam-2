"""평가 지도 하나를 진짜 모델로 돌려 과정을 보기 좋게 찍는다(시연용). 장소 이름은 화면에만 나오고 파일에 남기지 않는다.

    cd backend && .venv/bin/python -m agent.course.eval.demo <지도 번호> [--no-model] [--request "문장" | --requests 파일]

지도 번호는 `eval/data/maps/map_NN.json`의 NN(짝수는 월요일 시작 — 월요일 휴관 관광지가 걸린다).
모델 설정(ELICE_ML_API_*)은 backend/.env에서 읽는다. --no-model이면 코드 기준선으로만 돈다(0원).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Optional, Sequence

from agent.course import core, loop
from agent.course.eval.compare import Scenario, scenario_from_map, score
from agent.course.state import initial_state

LINE = "─" * 60
WEEKDAY = "월화수목금토일"


def format_course(sc: Scenario, course: core.Course, hours: dict) -> list[str]:
    out = []
    for i, day in enumerate(course):
        d = sc.trip.days[i]
        out.append(f"  {core.day_alias(i)} {d.isoformat()}({WEEKDAY[d.weekday()]}) — {len(day)}곳, 도보 합계 {core.day_travel(sc.trip, day)}분")
        for k, p in enumerate(day):
            place = sc.trip.place(p)
            status = core.status_on(hours, p, d)
            mark = {"closed": "  ✗ 이날 휴무", "unknown": "  ? 영업 확인 필요", "open": ""}[status]
            out.append(f"     {k + 1}. [{place.category}] {place.name}{mark}")
            if k + 1 < len(day):
                out.append(f"        ↓ 도보 {core.travel_minutes(sc.trip, p, day[k + 1])}분")
    return out


def describe_call(sc: Scenario, call: dict) -> str:
    name = lambda a: sc.trip.place(a).name if a in {p.alias for p in sc.trip.places} else a
    t = call["tool"]
    if t == "get_opening_hours": return f"영업시간 조회({name(call['place'])})"
    if t == "find_open_days": return f"영업하는 날 찾기({name(call['place'])})"
    if t == "estimate_travel": return f"도보 시간 계산({name(call['from_place'])} → {name(call['to_place'])})"
    if t == "try_move":
        m = call["move"]
        if m["type"] == "move_day": return f"시험: {name(m['place'])}를 {m['to_day']}로 옮기기"
        if m["type"] == "swap": return f"시험: {name(m['a'])} ↔ {name(m['b'])} 맞바꾸기"
        return f"시험: {m['day']} 순서 다시 짜기"
    if t == "commit_move": return f"채택({call['trial_id']})"
    if t == "revert": return f"되돌리기(단계 {call['to_step']})"
    return f"끝내기({call['reason_code']})"


def describe_result(r) -> str:
    if not r.ok:
        return f"✗ {r.error}"
    d = r.data or {}
    if "hard_after" in d:
        return f"하드 {d['hard_before']} → {d['hard_after']}"
    if "days" in d:
        return "영업: " + ", ".join(f"{k}={v}" for k, v in d["days"].items())
    if "walk_minutes" in d:
        return f"{d['walk_minutes']}분"
    if "hard" in d:
        return f"하드 {d['hard']}"
    return "ok"


def run(map_no: int, data: Path, use_model: bool, out=print) -> None:
    m = json.loads((data / "maps" / f"map_{map_no:02d}.json").read_text(encoding="utf-8"))
    sc = scenario_from_map(m)
    draft = core.draft_course(sc.trip)
    state = initial_state(sc.trip, sc.start_hours, draft)

    out(LINE)
    out(f"지도 {m['id']} — {len(m['days'])}일({m['days'][0]} ~ {m['days'][-1]}), 장소 {len(m['places'])}곳, "
        f"구성원 도보 조건 {'있음(하루 90분)' if m['member_constraints'] else '없음'}")
    closed = [p["name"] for p in m["places"] if any(core.status_on(sc.truth, p["alias"], d) == "closed" for d in sc.trip.days)]
    out(f"여행 기간에 쉬는 곳: {', '.join(closed) or '없음'}")
    out(LINE)
    out("▶ 초안 코스 (코드가 만든 첫 배치, 아는 영업시간 기준 표시)")
    out("\n".join(format_course(sc, draft, sc.start_hours)))
    v = core.find_violations(sc.trip, draft, sc.start_hours)
    out(f"  시작 때 보이는 위반 {len(v)}건, 확인 필요 {len(core.find_checks(sc.trip, draft, sc.start_hours))}곳")

    decide = None
    if use_model:
        from agent.course.deps import ModelDecider
        from llm.api import real_course_turn_planner
        decide = ModelDecider(real_course_turn_planner)
    out(LINE)
    out(f"▶ 에이전트 {'(진짜 모델)' if use_model else '(코드 기준선)'} — 턴마다 생각하고 도구를 쓴다")
    started = time.monotonic()
    result = loop.run_loop(state, decide=decide, hours=sc.gateway)
    elapsed = time.monotonic() - started
    for s in result.steps:
        who = "핑고" if s.by == "model" else "기준선"
        if s.substituted_for:
            out(f"[{s.turn:>2}] (모델의 {describe_call(sc, s.substituted_for['call'])}가 {s.substituted_for['error']}라 기준선이 대신함)")
        out(f"[{s.turn:>2}] {who}: {s.thought or ('(표시하지 않는 문장: ' + str(s.thought_problem) + ')' if s.by == 'model' else '규칙에 따라 실행')}")
        out(f"       → {describe_call(sc, s.call)}  ⇒ {describe_result(s.result)}{'  (직전과 같은 호출)' if s.repeated else ''}")

    out(LINE)
    out(f"▶ 최종 코스 — 결과: {result.outcome} (진짜 영업시간 기준 표시)")
    out("\n".join(format_course(sc, result.best_course, sc.truth)))
    final = score(sc, result.best_course, len(result.steps))
    left = core.find_violations(sc.trip, result.best_course, sc.truth)
    out(f"남은 위반: {', '.join(x.id for x in left if x.status == 'confirmed') or '없음'}")
    out(f"확인 필요(영업 여부를 끝까지 모름): {final.hard_unknown}곳 — 가게에 직접 확인하도록 안내한다")
    base = score(sc, draft)
    out(f"초안 대비: 확정 위반 {base.hard_confirmed} → {final.hard_confirmed}, 도보 합계 {base.soft['travel_total']} → {final.soft['travel_total']}분, "
        f"식사 후 카페 {base.soft['cafe_after_meal']} → {final.soft['cafe_after_meal']}")
    out(LINE)
    tail = f" · 모델 토큰 입력 {decide.tokens[0]:,} / 출력 {decide.tokens[1]:,} · 실패 {len(decide.failures)}회" if decide else ""
    out(f"걸린 시간 {elapsed:.1f}초 · 모델 턴 {result.model_turns} · 기준선 턴 {result.baseline_turns}{tail}")


def run_direct_demo(
    map_no: int, data: Path, use_model: bool, request: Optional[str] = None, requests_file: Optional[Path] = None, out=print,
) -> None:
    """요청 한 줄 → 목표 세우기 → 지휘 루프(optimize·질문·끝)를 돌리고 작업 기록(8.3 표 모양)을 찍는다.
    요청은 --request 문장이 먼저이고, 없으면 --requests 파일의 이 지도 문장이다. 모델 없이(--no-model)는 목표 세우기가 스텁이라
    --requests 파일의 정답 목표를 대신 넣는다(그 줄에 "정답 주입(스텁)"으로 밝힌다) — 문장을 직접 줬으면 스텁은 목표를 만들지 않는다."""
    from agent.course import direct, goals as goals_mod, worklog
    from agent.course.constants import REQUEST_TEXT_MAX_CHARS
    from agent.course.deps import DirectDecider, GoalSetter, ModelTurnFailed
    from agent.course.eval.compare import gold_goals

    m = json.loads((data / "maps" / f"map_{map_no:02d}.json").read_text(encoding="utf-8"))
    sc = scenario_from_map(m)
    req = None
    if requests_file is not None:
        req = next((r for r in json.loads(requests_file.read_text(encoding="utf-8")) if r["map_id"] == m["id"]), None)
    text = (request or (req["request_text"] if req else "")).strip()[:REQUEST_TEXT_MAX_CHARS]
    if not text:
        raise SystemExit("요청 문장이 없다: --request 문장 또는 --requests 파일(이 지도의 줄)을 준다")

    out(LINE)
    out(f"지도 {m['id']} — {len(m['days'])}일, 장소 {len(m['places'])}곳")
    out(f"요청: {text}")
    out(LINE)
    started = time.monotonic()
    setter = decider = None
    understood_by, unmatched = "모델", ()
    if use_model:
        from llm.api import real_course_direct_planner, real_course_goals_planner
        setter, decider = GoalSetter(real_course_goals_planner), DirectDecider(real_course_direct_planner)
        try:
            verified = goals_mod.verify_goal_set(sc.trip, text, setter(goals_mod.goals_input(sc.trip, text)))
            goals, unmatched = verified.goals, verified.unmatched
        except ModelTurnFailed:
            goals, unmatched, understood_by = (), (text,), "코드(목표 세우기 실패)"
    elif req is not None and not request:
        goals, unmatched, understood_by = gold_goals(sc, req), tuple(req["gold_unmatched"]), "정답 주입(스텁)"
    else:
        goals, unmatched, understood_by = (), (text,), "스텁"
    draft = core.draft_course(sc.trip)
    state = initial_state(sc.trip, sc.start_hours, draft, goals)
    result = direct.run_direct(state, decide=decider, hours=sc.gateway, unmatched_count=len(unmatched))
    out("\n".join(worklog.render(sc.trip, goals, unmatched, result, understood_by=understood_by)))
    out(LINE)
    out("▶ 최종 코스 (진짜 영업시간 기준 표시)")
    out("\n".join(format_course(sc, result.course, sc.truth)))
    elapsed = time.monotonic() - started
    tail = f" · 모델 호출 {setter.calls + decider.calls} · 토큰 입력 {setter.tokens[0] + decider.tokens[0]:,} / 출력 {setter.tokens[1] + decider.tokens[1]:,}" if setter else ""
    out(f"걸린 시간 {elapsed:.1f}초 · 지휘 모델 턴 {result.model_turns} · 질문 {len(result.questions)}{tail}")


def main(argv: Optional[Sequence[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("map_no", type=int)
    ap.add_argument("--data", type=Path, default=Path(__file__).parent / "data")
    ap.add_argument("--no-model", action="store_true")
    ap.add_argument("--request", default=None, help="요청 한 줄을 직접 넣는다(지휘 루프 시연)")
    ap.add_argument("--requests", type=Path, default=None, help="요청 문장 세트 파일 — 이 지도의 문장을 쓴다(지휘 루프 시연)")
    args = ap.parse_args(argv)
    if args.request or args.requests:
        run_direct_demo(args.map_no, args.data, not args.no_model, args.request, args.requests)
    else:
        run(args.map_no, args.data, not args.no_model)


if __name__ == "__main__":
    main()
