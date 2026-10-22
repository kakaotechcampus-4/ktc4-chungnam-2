"""검증이 지휘를 견제 — 화면에 나갈 모델 문장이 코드 사실과 어긋나면 코드 문장으로 바꾼다(다시 부르지 않는다)."""

import re
from dataclasses import replace

from agent.course import core, direct, goals as G, optimize as O, verify, worklog
from agent.course.state import initial_state
from agent.course.tests.fixtures import ALL_OPEN, PLACES, TRUE_HOURS, TUE, trip
from llm.schemas import CourseDirectTurn

P1_D2 = G.Goal("place_on_day", "d2", ("p1",))
COURSE = (("p2", "p6"), ("p1", "p3", "p4"), ("p5",))              # p1이 둘째 날(화), p4(화요일 휴무)도 둘째 날 — 확정 위반 1
HOURS = {p.alias: ALL_OPEN for p in PLACES}
HOURS["p4"] = {**ALL_OPEN, TUE.weekday(): "closed"}
NIGHT_D1 = G.Goal("night_end", "d1")


def ref(goals=(P1_D2,), course=COURSE, hours=None, t=None):
    t = t or trip()
    hours = hours if hours is not None else HOURS
    return verify.Reference(t, hours, course, core.find_violations(t, course, hours), tuple(goals), "후보", 1)


class TestClaims:
    def test_zero_violation_claim_is_blocked_when_one_remains(self):
        found = verify.problems(ref(), "후보가 요청 목표를 지키며 확정 위반도 없는 것을 확인해 이 코스를 고를게요.")
        assert len(found) == 1 and "확정 위반이 없다고 썼지만 결과에는 1개가 남아 있어요" in found[0]

    def test_zero_violation_claim_passes_when_none_remain(self):
        clean = ref(hours={p.alias: ALL_OPEN for p in PLACES})
        assert verify.problems(clean, "요청 목표를 지켰고 확정 위반도 없어 이 후보로 마무리해요.") == []
        assert verify.problems(clean, "{d1}의 휴무 위반은 모두 해결됐어요.") == []

    def test_remaining_claim_is_blocked_when_none_remain(self):
        clean = ref(hours={p.alias: ALL_OPEN for p in PLACES})
        assert verify.problems(clean, "확정 위반이 남아 있어서 다시 짜 볼게요.") != []
        assert verify.problems(ref(), "확정 위반이 남아 있어서 다시 짜 볼게요.") == []

    def test_violation_kind_scope(self):
        assert verify.problems(ref(), "휴무 위반은 해결됐어요.") != []          # 남은 위반이 휴무다
        assert verify.problems(ref(), "도보 위반은 없어요.") == []              # 도보 위반은 실제로 없다

    def test_intentions_and_questions_are_not_claims(self):
        for text in ("확정 위반이 없도록 다시 짜 볼게요.", "확정 위반이 없는지 먼저 확인해 볼게요.", "위반이 남아 있으면 다시 짜 볼게요."):
            assert verify.problems(ref(), text) == [], text

    def test_check_claim_uses_checks_left(self):
        unknown = ref(hours={**HOURS, "p3": {}})                                 # p3는 영업 여부를 모른다
        assert verify.problems(unknown, "요청하신 {d2} 배치가 지켜졌고 영업 확인도 통과한 후보라 선택해요.") != []
        sure = ref()
        assert verify.problems(sure, "요청하신 {d2} 배치가 지켜졌고 영업 확인도 통과한 후보라 선택해요.") == []

    def test_goal_claims(self):
        met = ref()                                                              # p1이 둘째 날 — 목표 충족
        assert verify.problems(met, "{p1}을 {d2}에 두는 목표를 지켰어요.") == []
        assert verify.problems(met, "{p1}을 {d2}에 두는 목표를 못 지켰어요.") != []
        miss = ref(goals=(G.Goal("place_on_day", "d1", ("p1",)),))
        assert verify.problems(miss, "{p1}을 {d1}에 두는 목표를 지켰어요.") != []
        assert verify.problems(miss, "{p1}을 {d1}에 두는 목표를 지키지 못했어요.") == []

    def test_goal_claims_by_topic(self):
        r = ref(goals=(P1_D2, NIGHT_D1))                                          # 야경(d1 마지막은 p6) 충족, p1 충족
        assert verify.problems(r, "야경 목표는 지켰지만 걷는 시간은 여전히 길어요.") == []
        far = ref(goals=(NIGHT_D1,), course=(("p6", "p2"), ("p1", "p3", "p4"), ("p5",)))     # d1 마지막이 p2 — 야경 못 지킴
        assert verify.problems(far, "야경 목표를 지켰어요.") != []
        assert verify.problems(far, "야경은 못 지켰지만 다른 건 맞춰요.") == []

    def test_conditional_goal_words_are_not_claims(self):
        far = ref(goals=(NIGHT_D1,), course=(("p6", "p2"), ("p1", "p3", "p4"), ("p5",)))
        assert verify.problems(far, "야경을 지키면 둘째 날 걷는 시간이 길어져서 다시 짜 볼게요.") == []

    def test_closed_day_claims(self):
        r = ref()
        assert verify.problems(r, "{p4}이 {d2}에 쉬어서 옮길지 여쭤볼게요.") == []
        assert verify.problems(r, "{p4}이 {d2}에 열어서 그대로 둬요.") != []
        assert verify.problems(r, "{p4}이 {d2}에 쉬지 않아요.") != []
        assert verify.problems(r, "{p1}이 {d2}에 쉬어요.") != []
        assert verify.problems(r, "{p4}을 {d2}에 두는 건 가능해요.") != []
        assert verify.problems(r, "{p4}을 {d1}에 두는 건 가능해요.") == []

    def test_unknown_hours_cannot_be_called_open(self):
        r = ref(hours={**HOURS, "p3": {}})
        assert verify.problems(r, "{p3}이 {d2}에 열어요.") != []

    def test_numbers_must_match_code_values(self):
        r = ref()                                                                 # 확정 위반 1, 장소 6, 날짜 3, 목표 1
        assert verify.problems(r, "위반이 아홉 곳 남아 있어요.") != []
        assert verify.problems(r, "위반이 한 곳 남아 있어요.") == []
        assert verify.problems(r, "삼백 분 넘게 걸어요.") != []
        assert verify.problems(r, "하루에 사십 분까지만 걷게 해요.") == []         # 구간 상한 40분은 코드 값이다
        assert verify.problems(r, "이 곳은 쉬어요.") == []                          # 지시어 "이 곳"은 수가 아니다

    def test_unverifiable_sentences_pass(self):
        for text in ("해 볼게요.", "걷는 시간이 길어서 걷기 목표를 먼저 두고 다시 짜 볼게요.", "요청하신 날짜를 옮길지 여쭤볼게요."):
            assert verify.problems(ref(), text) == [], text


class TestFactSentence:
    def test_names_remaining_violation(self):
        text = verify.fact_sentence(ref())
        assert text.startswith("확정 위반 1개가 남은 후보예요. 남은 위반: 장소P4이름이 둘째 날 (화) 휴무.")
        assert "지킨 목표: 장소P1이름을 둘째 날 (화)에" in text and "못 지킨 목표" not in text

    def test_zero_violations_and_checks(self):
        text = verify.fact_sentence(ref(hours={**{p.alias: ALL_OPEN for p in PLACES}, "p3": {}}))
        assert text.startswith("확정 위반이 없는 후보예요.") and "영업 확인이 필요한 곳은 1곳이에요." in text

    def test_particles_follow_the_real_name(self):
        named = [replace(p, name="책보고") if p.alias == "p4" else p for p in PLACES]
        assert "책보고가 둘째 날 (화) 휴무" in verify.fact_sentence(ref(t=trip(places=tuple(named))))
        named = [replace(p, name="플랫폼엘") if p.alias == "p4" else p for p in PLACES]
        assert "플랫폼엘이 둘째 날 (화) 휴무" in verify.fact_sentence(ref(t=trip(places=tuple(named))))

    def test_walk_violation_text(self):
        far = [replace(p, lat=37.5665 + 0.3 * i) for i, p in enumerate(PLACES)]     # 장소 사이가 멀다(구간마다 대중교통 약 100분)
        t = trip(places=tuple(far))
        r = ref(t=t, course=(("p1", "p2", "p3"), ("p4", "p5"), ("p6",)), hours={p.alias: ALL_OPEN for p in PLACES})
        text = verify.fact_sentence(r)
        assert "하루 이동 합계" in text and "대중교통 포함" in text


# ---- 지휘 루프 안에서 ----

def turn(thought, **action):
    return CourseDirectTurn.model_validate({"thought": thought, "action": action})


def run(thoughts_and_actions, monkeypatch, goals=(P1_D2,), course=COURSE):
    st = initial_state(trip(), HOURS, course, tuple(goals))
    cand = O.Candidate("c1", course, core.find_violations(st.trip, course, HOURS), ())
    monkeypatch.setattr(direct.opt, "optimize", lambda s, **kw: (s, (cand,)))
    queue = [turn(t, **a) for t, a in thoughts_and_actions]
    calls = []

    def decide(turn_input):
        calls.append(turn_input)
        return queue.pop(0)

    result = direct.run_direct(st, decide=decide, hours=TRUE_HOURS)
    return st, result, calls


OPT = {"tool": "optimize", "priority": [], "locks": []}
FIN = {"tool": "finish", "candidate_id": "c1"}
MAP04 = "{p1}이 {d2}에 열고 후보가 요청 목표를 지키며 확정 위반도 없는 것을 확인해 이 코스를 고를게요."


def test_map_04_contradiction_is_replaced_by_a_code_sentence(monkeypatch):
    st, result, calls = run([("해 볼게요.", OPT), (MAP04, FIN)], monkeypatch)
    finish = result.steps[-1]
    assert finish.guard and finish.blocked_thought == MAP04
    assert finish.thought.startswith("확정 위반 1개가 남은 후보예요. 남은 위반: 장소P4이름이 둘째 날 (화) 휴무")
    lines = worklog.render(st.trip, [P1_D2], [], result)
    text = "\n".join(lines)
    assert "확정 위반도 없는 것을 확인해" not in text and "고를게요" not in text                     # 모델 문장은 화면에 없다
    notice = next(l for l in lines if l.startswith("[검증]"))
    assert notice.startswith("[검증] 검증(코드) 모델이 쓴 문장이 결과와 맞지 않아") and "1개가 남아 있어요" in notice
    replaced = lines[lines.index(notice) + 1]
    assert replaced.startswith("[점검] 지휘(코드) 확정 위반 1개가 남은 후보예요")
    assert result.guarded == 1 and len(calls) == 2                                                   # 모델을 다시 부르지 않았다


def test_a_correct_sentence_passes_through_unchanged(monkeypatch):
    ok = "{p1}을 {d2}에 두는 목표는 지켰지만 확정 위반이 남아 있어 이 후보로 마무리해요."
    st, result, calls = run([("해 볼게요.", OPT), (ok, FIN)], monkeypatch)
    finish = result.steps[-1]
    assert finish.guard == () and finish.blocked_thought is None and result.guarded == 0
    assert finish.thought == "장소P1이름을 둘째 날 (화)에 두는 목표는 지켰지만 확정 위반이 남아 있어 이 후보로 마무리해요."
    lines = worklog.render(st.trip, [P1_D2], [], result)
    assert not any(l.startswith("[검증]") for l in lines)
    assert any(l == "[점검] 지휘(모델) " + finish.thought for l in lines)


def test_number_words_that_do_not_match_are_blocked_in_the_loop(monkeypatch):
    _, result, _ = run([("해 볼게요.", OPT), ("위반 아홉 곳이 남았지만 이 후보로 마무리해요.", FIN)], monkeypatch)
    assert result.steps[-1].guard and "아홉 곳" in result.steps[-1].guard[0]


def test_replan_sentence_is_checked_against_the_candidates_the_model_saw(monkeypatch):
    # 첫 optimize 뒤의 재계획 문장 — 후보가 이미 있으니 그 후보의 사실로 견준다
    st, result, _ = run([("해 볼게요.", OPT), ("확정 위반이 모두 해결돼서 한 번 더 짜 볼게요.", OPT), ("남은 위반을 받아들이고 끝내요.", FIN)], monkeypatch)
    replanned = [s for s in result.steps if s.call.get("tool") == "optimize" and s.turn == 2][0]
    assert replanned.guard and replanned.thought.startswith("확정 위반 1개가 남은 후보예요")
    lines = worklog.render(st.trip, [P1_D2], [], result)
    assert any(l.startswith("[재계획] 지휘(코드) 확정 위반 1개가 남은 후보예요") for l in lines)


def test_before_the_first_optimize_the_draft_is_the_reference(monkeypatch):
    _, result, _ = run([("확정 위반도 없어서 바로 짜 볼게요.", OPT), (FIN and "끝내요.", FIN)], monkeypatch)
    first = next(s for s in result.steps if s.turn == 1)
    assert first.guard and first.thought.startswith("확정 위반 1개가 남은 초안이에요")


class TestRoleLabels:
    LINE = re.compile(r"^\[[^\]]+\] (해석|지휘|계산|검증|결정)\(.+?\) \S")

    def test_every_line_has_a_role_and_a_who(self, monkeypatch):
        st, result, _ = run([("해 볼게요.", OPT), (MAP04, FIN)], monkeypatch)
        lines = worklog.render(st.trip, [P1_D2], ["웨이팅 없는 곳"], result)
        assert all(self.LINE.match(l) for l in lines), [l for l in lines if not self.LINE.match(l)]

    def test_roles_by_stage(self, monkeypatch):
        st, result, _ = run([("해 볼게요.", OPT), ("괜찮아서 마무리해요.", FIN)], monkeypatch)
        lines = worklog.render(st.trip, [P1_D2], [], result)
        role = lambda stage, who=None: next(l for l in lines if l.startswith(f"[{stage}]") and (who is None or who in l)).split(" ")[1]
        assert role("이해").startswith("해석(") and role("확인").startswith("검증(코드)")
        assert role("짜기", "후보").startswith("계산(코드)") and role("끝").startswith("지휘(모델)")
        assert next(l for l in lines if l.startswith("[결과]")).split(" ")[1] == "검증(코드)"


class TestModelVocabulary:
    """실모델이 "확정 위반" 대신 쓴 말(시연 v8): 확정 조건, 확정 관련 문제, 점검 통과."""

    def test_confirmed_condition_wording_counts_as_violation_claim(self):
        for text in ("요청한 날짜 배치 목표가 충족됐고 확정 조건도 지킨 후보라 이 코스로 마무리해요.",
                     "요청하신 배치가 지켜졌고 확정 관련 문제도 없어 이 코스로 마무리해요.",
                     "요청한 목표를 지키고 확정 위반도 없는 후보라서 선택할게요."):
            assert verify.problems(ref(), text) != [], text
        clean = ref(hours={p.alias: ALL_OPEN for p in PLACES})
        for text in ("요청한 날짜 배치 목표가 충족됐고 확정 조건도 지킨 후보라 이 코스로 마무리해요.",
                     "요청하신 배치가 지켜졌고 확정 관련 문제도 없어 이 코스로 마무리해요."):
            assert verify.problems(clean, text) == [], text

    def test_goal_met_clause_next_to_hard_clause_is_judged_separately(self):
        text = "요청한 날짜 배치 목표가 충족됐고 확정 조건도 지킨 후보라 이 코스로 마무리해요."
        assert verify.problems(ref(goals=(G.Goal("place_on_day", "d1", ("p1",)),)), text) != []   # 목표도 못 지켰다 → 이유 둘
        assert len(verify.problems(ref(goals=(G.Goal("place_on_day", "d1", ("p1",)),)), text)) >= 1

    def test_passed_inspection_claim(self):
        text = "요청한 날짜 배치가 지켜졌고 점검도 통과한 후보라 이 코스로 마무리할게요."
        assert verify.problems(ref(), text) != []                                                  # 확정 위반 1
        unknown = ref(hours={**{p.alias: ALL_OPEN for p in PLACES}, "p3": {}})
        assert "영업 확인이 필요한 곳 1곳" in verify.problems(unknown, text)[0] and "확정 위반" not in verify.problems(unknown, text)[0]
        assert verify.problems(ref(hours={p.alias: ALL_OPEN for p in PLACES}), text) == []

    def test_guarded_vocabulary_in_the_loop(self, monkeypatch):
        _, result, _ = run([("해 볼게요.", OPT), ("요청한 날짜 배치 목표가 충족됐고 확정 조건도 지킨 후보라 이 코스로 마무리해요.", FIN)], monkeypatch)
        assert result.steps[-1].guard and result.steps[-1].thought.startswith("확정 위반 1개가 남은 후보예요")


class TestDayHasClaims:
    PERF = G.Goal("day_has", "d2", (), "performance")

    def labeled_ref(self, with_perf):
        places = tuple(p if p.alias != "p1" else core.Place(p.alias, p.pin_id, p.place_id, p.name, p.category, p.lat, p.lng,
                                                              frozenset({"performance"} if with_perf else {"quiet"})) for p in PLACES)
        return ref(goals=(self.PERF,), t=trip(places=places))

    def test_keeping_claim_is_blocked_when_no_performance_place_is_on_the_day(self):
        found = verify.problems(self.labeled_ref(with_perf=False), "{d2}에 공연 장소를 넣는 목표를 지켰어요.")
        assert found and "공연 장소 넣기" in found[0]

    def test_keeping_claim_passes_and_gave_up_claim_is_blocked_when_met(self):
        r = self.labeled_ref(with_perf=True)                                      # p1이 둘째 날(COURSE)이라 지켜진다
        assert verify.problems(r, "{d2}에 공연 장소를 넣는 목표를 지켰어요.") == []
        assert verify.problems(r, "공연 목표는 못 지켰어요.") != []
