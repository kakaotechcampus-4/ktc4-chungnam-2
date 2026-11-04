"""후속 관찰과 충돌 선언(명세 6.9, #1346, 결정 #1345) — 순수 함수. DB 없이 스냅샷과 이력을 조립한다.

- episode_state 표(풀림·그대로·아직) — 유형마다
- detect_followups: 지켜보는 수락한 제안만, 닫음·만료는 후속 없음, 사슬의 해 본 것, 남은 행동이 없으면 충돌 선언
- 허용 행동에서 해 본 것이 빠진다, 0곳이면 추천 받기도 빠진다
- 순위: 후속 신호를 먼저(followup_first), 모델 상한은 다음 방법만 센다
- 충돌 선언 템플릿: 버튼 없음, 금지 표현(확정 지시, 조건 완화) 없음
- run 결과(비공개)는 진단 입력과 문구에 없다
"""

import json
from dataclasses import replace
from datetime import timedelta

import pytest

from agent import core
from agent.constants import FOLLOWUP_MIN_WAIT, MAX_ATTEMPT, STALL_ACTIVE_MEMBERS, TRACKING_WINDOW
from agent.tests.snaps import NOW, hours, item, pin, react, snap

TH = hours(3)
A = NOW - hours(1)   # 수락 시각(기준 시각 a)
WAITED = A + FOLLOWUP_MIN_WAIT


def accepted(diagnosis="stall", *, category="음식점", pin_id=None, sid="s_a", at=A, action="open_recommend",
             label=None, attempt=0, followup_of=None, status="accepted", watching=True, fp="fp_a"):
    label = label or {"open_recommend": f"{category} 추천 받기", "search_place": f"{category} 검색"}[action]
    return core.PastSuggestion(
        id=sid, diagnosis=diagnosis, category=category, fingerprint=fp, status=status, created_at=at - hours(1),
        resolved_at=at if status != "active" else None, expires_at=at + hours(23), pin_id=pin_id,
        resolved_action_type=action if status == "accepted" else None,
        resolved_action_label=label if status == "accepted" else None, attempt=attempt, followup_of=followup_of,
        followup=core.followup_record("watching", at) if watching else None,
    )


def stall_snap(*, extra_pins=(), extra_reactions=(), shortlist=(), last_run_at=None):
    """음식점 f1에 🚫 하나(수락 전), 카페 c1·c2는 다른 카테고리 활동용."""
    pins = [pin("f1"), pin("c1", category="카페"), pin("c2", category="카페"), *extra_pins]
    reactions = [react("r1", "f1", "u1", "against", A - hours(3)), *extra_reactions]
    return snap(pins=pins, reactions=reactions, shortlist=shortlist, last_run_at=last_run_at)


def two_actors(at):
    return [react("a2", "c1", "u2", "like", at), react("a3", "c2", "u3", "like", at)]


# ---------------------------------------------------------------- episode_state 표

def test_stall_waits_for_the_minimum_even_with_activity():
    """최소 대기(30분) 안의 활동은 세지 않는다 — 추천을 받고 올릴지 정할 시간이다."""
    s = stall_snap(extra_reactions=two_actors(A + timedelta(minutes=5)))
    assert core.episode_state(accepted(), s, A + timedelta(minutes=20), TH).status == "waiting"
    assert core.episode_state(accepted(), s, NOW, TH).status == "waiting"   # 활동이 최소 대기 전이라 세지 않는다


def test_stall_is_stuck_by_activity_after_the_wait():
    s = stall_snap(extra_reactions=two_actors(WAITED + timedelta(minutes=1)))
    assert core.episode_state(accepted(), s, NOW, TH) == core.EpisodeState("stuck", "activity")
    assert STALL_ACTIVE_MEMBERS == 2
    one = stall_snap(extra_reactions=two_actors(WAITED + timedelta(minutes=1))[:1])
    assert core.episode_state(accepted(), one, NOW, TH).status == "waiting"


def test_stall_is_stuck_by_time():
    assert core.episode_state(accepted(), stall_snap(), A + TH, TH) == core.EpisodeState("stuck", "time")
    assert core.episode_state(accepted(), stall_snap(), A + TH - timedelta(seconds=1), TH).status == "waiting"


def test_stall_activity_in_the_same_category_does_not_count():
    same = [react("a2", "f1", "u2", "like", WAITED + timedelta(minutes=1)),
            react("a3", "f1", "u3", "like", WAITED + timedelta(minutes=1))]
    assert core.episode_state(accepted(), stall_snap(extra_reactions=same), NOW, TH).status == "waiting"


@pytest.mark.parametrize(("kw", "reason"), [
    ({"extra_pins": [pin("f2", at=A + timedelta(minutes=10))]}, "new_pin"),
    ({"shortlist": [item("f1", at=A + timedelta(minutes=10))]}, "confirmed"),
])
def test_stall_is_resolved_by_new_pin_or_confirmation(kw, reason):
    s = stall_snap(extra_reactions=two_actors(WAITED + timedelta(minutes=1)), **kw)
    assert core.episode_state(accepted(), s, NOW, TH) == core.EpisodeState("resolved", reason)


def test_stall_pin_before_acceptance_does_not_resolve():
    s = stall_snap(extra_pins=[pin("f2", at=A - timedelta(minutes=1))])
    assert core.episode_state(accepted(), s, A + TH, TH).status == "stuck"


def test_a_run_alone_does_not_resolve():
    """「추천 받기」를 눌렀어도(run이 있어도) 아무도 지도에 올리지 않았으면 그대로다 — run 여부는 보지 않는다."""
    s = stall_snap(last_run_at={"음식점": A + timedelta(minutes=2)})
    assert core.episode_state(accepted(), s, A + TH, TH).status == "stuck"


def split_snap(*, like=2, against=1, shortlist=(), pins_extra=()):
    reactions = [react(f"l{i}", "p1", f"u{i + 1}", "like", A - hours(5)) for i in range(like)]
    reactions += [react(f"x{i}", "p1", f"u{like + i + 1}", "against", A - hours(5)) for i in range(against)]
    return snap(members=("u1", "u2", "u3", "u4"), pins=[pin("p1"), pin("p2"), pin("c1", category="카페"), *pins_extra],
                reactions=reactions, shortlist=shortlist)


def split_target(**kw):
    return accepted("split", pin_id="p1", **kw)


@pytest.mark.parametrize(("s", "reason"), [
    (split_snap(shortlist=[item("p1", at=A + timedelta(minutes=5))]), "confirmed"),
    (split_snap(shortlist=[item("p2", at=A + timedelta(minutes=5))]), "confirmed"),   # 같은 카테고리의 다른 핀
    (split_snap(against=0), "split_gone"),
    (snap(pins=[pin("p2")]), "pin_removed"),
])
def test_split_resolutions(s, reason):
    assert core.episode_state(split_target(), s, NOW, TH) == core.EpisodeState("resolved", reason)


def test_split_same_category_confirmation_before_acceptance_does_not_resolve():
    s = split_snap(shortlist=[item("p2", at=A - timedelta(minutes=5))])
    assert core.episode_state(split_target(), s, A + TH, TH) == core.EpisodeState("stuck", "time")


def test_category_gap_is_resolved_only_by_confirmation():
    base = [item("f1", at=A - hours(5)), item("c1", at=A - hours(5))]
    s = snap(pins=[pin("f1"), pin("c1", category="카페"), pin("t1", category="관광지", at=A + timedelta(minutes=5))],
             shortlist=base)
    target = accepted("category_gap", category="관광지")
    assert core.episode_state(target, s, A + TH, TH).status == "stuck"   # 새 핀만으로는 풀리지 않는다
    done = replace(s, shortlist=(*base, item("t1", at=A + timedelta(minutes=10))))
    done = snap(pins=s.pins, shortlist=done.shortlist)
    assert core.episode_state(target, done, A + TH, TH) == core.EpisodeState("resolved", "confirmed")


def test_decided_within_24h_uses_the_same_confirmation_rule():
    """측정(12.9)과 실시간 판정이 같은 규칙(core.is_decided)이다."""
    target = core.DecisionTarget(id="x", diagnosis="split", category="음식점", pin_id="p1", claims=[], actions=[],
                                 created_at=A)
    other = core.Confirmation(pin_id="p2", category="음식점", added_at=A + timedelta(minutes=5))
    assert core.decided_within_24h(target, [other]) is True
    s = split_snap(shortlist=[item("p2", at=A + timedelta(minutes=5))])
    assert core.episode_state(split_target(), s, NOW, TH).reason == "confirmed"


# ---------------------------------------------------------------- detect_followups

def _hist(*suggestions, runs_today=0):
    return core.History(suggestions=tuple(suggestions), model_runs_today=runs_today)


def stuck_snap():
    return stall_snap(extra_reactions=two_actors(WAITED + timedelta(minutes=1)))


def test_stuck_accepted_suggestion_becomes_a_followup_signal():
    scan = core.detect_followups(stuck_snap(), _hist(accepted()), NOW, TH)
    [sig] = scan.signals
    assert (sig.diagnosis, sig.category, sig.features["attempt"]) == ("stall", "음식점", 1)
    assert sig.features["tried"] == [{"action_type": "open_recommend", "label": "음식점 추천 받기",
                                      "accepted_at": A.isoformat()}]
    assert sig.features["followup_of"] == "s_a"
    assert core.followup_check_result(sig) == {"since_minutes": 60, "new_pins": 0}
    assert sig.evidence_ids == ("r1",)
    assert sig.fingerprint != "fp_a" and sig.fingerprint == core._digest(["fp_a", 1])
    json.dumps(core.signal_record(sig))   # agent_runs.signals에 그대로 들어간다(JSON)
    assert scan.resolved == ()


@pytest.mark.parametrize("status", ["dismissed", "expired", "superseded"])
def test_dismissed_or_expired_suggestions_are_not_followed(status):
    """사람이 닫았거나(그 판단을 존중) 아무도 누르지 않은 제안은 지켜보지 않는다 — followup이 없다."""
    h = accepted(status=status, watching=False)
    assert core.detect_followups(stuck_snap(), _hist(h), NOW, TH) == core.FollowupScan()


def test_no_reaction_is_never_followed():
    h = accepted("no_reaction", category=None, action="open_recommend", label="핀 보기")
    assert core.detect_followups(stuck_snap(), _hist(h), NOW, TH) == core.FollowupScan()
    assert core.watch_on_accept("no_reaction", 0, NOW) is None


def test_watch_on_accept():
    assert core.watch_on_accept("stall", 0, NOW) == {"status": "watching", "at": NOW.isoformat()}
    assert core.watch_on_accept("category_gap", 1, NOW)["status"] == "watching"
    assert core.watch_on_accept("stall", MAX_ATTEMPT, NOW) is None   # 충돌 선언은 버튼이 없다


def test_followed_up_suggestion_is_not_followed_again():
    h = replace(accepted(), followup=core.followup_record("followed_up", NOW))
    assert core.detect_followups(stuck_snap(), _hist(h), NOW, TH).signals == ()


def test_resolved_episode_is_reported():
    s = stall_snap(extra_pins=[pin("f2", at=A + timedelta(minutes=10))])
    assert core.detect_followups(s, _hist(accepted()), NOW, TH).resolved == (("s_a", "new_pin"),)


def test_second_followup_after_two_tries_is_a_declaration():
    first = accepted(sid="s0", at=A - hours(2), watching=False)
    first = replace(first, followup=core.followup_record("followed_up", A))
    second = accepted(sid="s1", action="search_place", attempt=1, followup_of="s0", fp="fp_1")
    [sig] = core.detect_followups(stuck_snap(), _hist(second, first), NOW, TH).signals
    assert sig.features["attempt"] == MAX_ATTEMPT
    assert [t["action_type"] for t in sig.features["tried"]] == ["open_recommend", "search_place"]
    assert not core.uses_model(sig)


def test_no_remaining_action_skips_to_declaration():
    """카테고리 공백이 추천 대상이 아니면 허용 행동이 검색 하나다 — 그걸 해 봤으면 다음 방법 없이 충돌 선언."""
    target = accepted("category_gap", category="숙소", action="search_place")
    assert core.base_actions("category_gap", "숙소") == ("search_place",)
    s = snap(pins=[pin("f1"), pin("c1", category="카페")], shortlist=[item("f1"), item("c1")])
    [sig] = core.detect_followups(s, _hist(target), A + TH, TH).signals
    assert sig.features["attempt"] == MAX_ATTEMPT


def test_active_followup_is_superseded_only_when_resolved():
    prev = replace(accepted(sid="s0"), followup=core.followup_record("followed_up", NOW))
    active = replace(accepted(sid="s1", status="active", watching=False, attempt=1, followup_of="s0", fp="fp_1"),
                     expires_at=NOW + hours(20))
    hist = _hist(active, prev)
    assert core.detect_followups(stuck_snap(), hist, NOW, TH).resolved == ()
    assert core.find_superseded(active, [], ()) == []   # 탐지기가 다시 찾지 않아도 무효화하지 않는다
    resolved = stall_snap(extra_pins=[pin("f2", at=A + timedelta(minutes=10))])
    scan = core.detect_followups(resolved, hist, NOW, TH)
    assert scan.resolved == (("s1", "new_pin"),)
    assert core.find_superseded(active, [], dict(scan.resolved)) == ["s1"]


# ---------------------------------------------------------------- 허용 행동, 순위, 상한

def _followup(attempt=1, tried=("open_recommend",), diagnosis="stall", category="음식점"):
    [sig] = core.detect_followups(stuck_snap(), _hist(accepted()), NOW, TH).signals
    features = dict(sig.features) | {
        "attempt": attempt, "tried": [{"action_type": t, "label": t, "accepted_at": A.isoformat()} for t in tried]}
    return replace(sig, diagnosis=diagnosis, category=category, features=features)


def test_allowed_actions_drop_what_was_tried():
    assert core.allowed_actions(_followup()) == ("search_place",)
    assert core.allowed_actions(_followup(tried=("search_place",))) == ("open_recommend",)
    assert core.allowed_actions(_followup(tried=("open_recommend", "search_place"))) == ()
    assert core.allowed_actions(_followup(tried=("search_place",)), {"passed_count": 0}) == ()   # 0곳 추천은 권하지 않는다
    first = core.detect_stall(stall_snap(), A + TH, TH)
    assert first and core.allowed_actions(first[0]) == core.MODEL_ACTIONS["stall"]   # 첫 제안은 그대로


def test_model_action_check_rejects_a_tried_action():
    sig = _followup()
    kept = {"c1": object()}
    action = type("A", (), {"type": "open_recommend", "basis": ["c1"], "category": None})()
    assert core._model_action(action, sig, kept) == (None, "type")
    action.type = "search_place"
    assert core._model_action(action, sig, kept)[0] == ("search_place", "음식점 검색", {"category": "음식점"})


def test_followup_signals_are_ranked_first():
    policy = core.PriorityPolicy(version=1, urgent_dday=3, never_first=(), always_first=("category_gap",),
                                 weights={"stall": 3, "split": 4, "no_reaction": 1, "category_gap": 2})
    gap = core.make_signal("category_gap", category="카페", evidence=[], features={"dday": 30})
    split = core.make_signal("split", category="음식점", evidence=[], features={"affected_members": 3})
    follow = replace(_followup(), id="s3")
    order, hits = core.rank_signals([replace(gap, id="s1"), replace(split, id="s2"), follow], policy)
    assert order[0] is follow and hits[-1] == "followup_first"
    _, log = core.choose_top([replace(gap, id="s1"), follow], policy)
    assert log["final_order"][0] == "s3" and "followup_first" in log["rule_hits"]


def test_model_cap_counts_next_method_but_not_declaration():
    s = stuck_snap()
    hist = _hist(runs_today=99)
    nxt, declare = replace(_followup(), id="s1"), replace(_followup(attempt=MAX_ATTEMPT), id="s2")
    passed, blocked = core.check_policy([nxt, declare], hist, s, NOW)
    assert [b.signal_id for b in blocked if b.reason == "model_cap"] == ["s1"]
    assert [p.id for p in passed] == ["s2"]


def test_next_check_includes_the_watch_times():
    s = stall_snap()
    at = core.next_check_at(s, _hist(accepted()), A + timedelta(minutes=1), TH)
    assert at == A + FOLLOWUP_MIN_WAIT
    assert core.next_check_at(s, _hist(accepted()), WAITED + timedelta(minutes=1), TH) <= A + TH


# ---------------------------------------------------------------- 진단 입력: 해 본 것, 비공개 run 없음

def test_diagnosis_input_carries_attempts_and_allowed_actions_but_no_run():
    sig = replace(_followup(), id="s1")
    s = stall_snap(last_run_at={"음식점": A + timedelta(minutes=2)})
    inp = core.diagnosis_input(sig, s, preview={"passed_count": 4, "funnel": {"secret": 1}})
    assert inp["attempt"] == 1
    assert inp["attempts"] == [{"action": "open_recommend", "label": "open_recommend"}]
    assert inp["allowed_actions"] == ["search_place"]
    dumped = json.dumps(inp, ensure_ascii=False, default=str)
    for leak in ("run", "resolved_by", "last_run_at", "funnel"):
        assert leak not in dumped


def test_first_suggestion_input_is_unchanged():
    [sig] = core.detect_stall(stall_snap(), A + TH, TH)
    inp = core.diagnosis_input(replace(sig, id="s1"), stall_snap())
    assert not {"attempt", "attempts", "allowed_actions"} & set(inp)


# ---------------------------------------------------------------- 충돌 선언 템플릿

def _declare(preview=None, tried=("open_recommend", "search_place")):
    labels = {"open_recommend": "음식점 추천 받기", "search_place": "음식점 검색"}
    sig = _followup(attempt=MAX_ATTEMPT, tried=tried)
    sig = replace(sig, features=dict(sig.features) | {"tried": [
        {"action_type": t, "label": labels[t], "accepted_at": A.isoformat()} for t in tried]})
    return core.render_followup_template(sig, preview)


def _render(draft):
    claims = {c["id"]: c for c in draft.claims}
    return [core.render_segments(line["slot_text"], claims, core.RenderRefs(pin_names={})) for line in draft.advice]


def test_declaration_lists_what_was_tried_and_has_no_buttons():
    draft = _declare({"passed_count": 3})
    assert draft.actions == []
    assert draft.title == "음식점에서 해 본 것을 남겨 둘게요"
    texts = ["".join(seg.text for seg in segs) for segs in _render(draft)]
    assert texts == ["음식점 추천 받기를 해 봤어요", "음식점 검색을 해 봤어요", "지금 조건으로 미리 찾아보면 3곳이 남아요",
                     core.DECLARE_CLOSING]
    assert draft.claims == [{"id": "c1", "kind": "tool_result", "call_id": "p1", "path": "passed_count", "value": 3}]


def test_declaration_without_preview_has_no_count():
    texts = ["".join(seg.text for seg in segs) for segs in _render(_declare(None))]
    assert texts[-1] == core.DECLARE_CLOSING and not any(ch.isdigit() for t in texts for ch in t)


def test_declaration_never_relaxes_or_orders():
    """가드레일 4 — 조건 완화를 말하지 않는다. 확정 지시도 없다. 템플릿 문장 전부와 제목에 건다."""
    draft = _declare({"passed_count": 0})
    said = "".join([draft.title] + [line["slot_text"] for line in draft.advice])
    for phrase in core.DECLARE_FORBIDDEN:
        assert core._squash(phrase) not in core._squash(said), phrase
    assert "조건" in core.DECLARE_CLOSING and "때문" not in said


def test_declaration_template_drops_a_line_with_forbidden_phrase(monkeypatch):
    monkeypatch.setattr(core, "DECLARE_CLOSING", "반경을 넓혀 보세요")
    texts = [line["slot_text"] for line in _declare(None).advice]
    assert "반경을 넓혀 보세요" not in texts


def test_category_gap_next_method_is_a_template_with_the_remaining_action():
    sig = _followup(diagnosis="category_gap", category="카페")
    sig = replace(sig, features=dict(sig.features) | {"tried": [
        {"action_type": "open_recommend", "label": "카페 추천 받기", "accepted_at": A.isoformat()}]})
    sig = replace(sig, evidence_ids=("f1", "c9"))
    draft = core.render_followup_template(sig)
    assert [(a["type"], a["label"]) for a in draft.actions] == [("search_place", "카페 검색")]
    assert draft.advice[0]["slot_text"] == "카페 추천 받기를 해 봤어요"
    with pytest.raises(ValueError):
        core.render_followup_template(_followup())   # 모델 유형의 다음 방법은 진단이 만든다


# ---------------------------------------------------------------- 작업 기록과 지켜보는 줄

def test_followup_step_reads_numbers_from_f1():
    sig = replace(_followup(), id="s1")
    run = type("Run", (), {
        "signals": [core.signal_record(sig)], "priority": {"source": "single"},
        "tool_calls": [{"call_id": "f1", "name": "followup_check", "args": {}, "result": {"since_minutes": 300,
                                                                                       "new_pins": 0}}],
        "verification": None})()
    sug = type("Sug", (), {"fingerprint": sig.fingerprint, "facts": []})()
    steps = core.render_steps(run, sug)
    assert [(st.stage, st.text) for st in steps][:2] == [
        ("감지", "음식점에 반대 의견 1개가 남은 뒤로 새 후보가 없어요"),
        ("후속 확인", "추천 받기 뒤로 5시간 동안 음식점에 새 핀이 없었어요"),
    ]
    assert steps[-1].stage == "재확인"


def test_tracking_lists_watching_resolved_and_declared_but_not_active_or_dismissed():
    watching = accepted(sid="w")
    resolved = replace(accepted(sid="r", category="카페"),
                       followup=core.followup_record("resolved", NOW - hours(1), "new_pin"))
    declared = replace(accepted(sid="d", status="expired", watching=False, attempt=2),
                       followup=core.followup_record("declared", NOW - hours(2)))
    active_declared = replace(accepted(sid="ad", status="active", watching=False, attempt=2),
                              followup=core.followup_record("declared", NOW))
    dismissed = accepted(sid="x", status="dismissed", watching=False)
    old = replace(accepted(sid="o"), followup=core.followup_record("watching", NOW - TRACKING_WINDOW - hours(1)))
    out = core.tracking([watching, resolved, declared, active_declared, dismissed, old], NOW)
    assert [(t.suggestion_id, t.status, t.text) for t in out] == [
        ("w", "watching", "음식점 · 추천 받기 뒤로 지켜보는 중"),
        ("r", "resolved", "카페 · 풀렸어요 — 새 핀이 올라왔어요"),
        ("d", "declared", "음식점 · 해 본 것을 남겼어요"),
    ]
    assert [t.label for t in out[0].tried] == ["음식점 추천 받기"]
