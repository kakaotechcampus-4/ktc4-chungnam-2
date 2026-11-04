"""AI 코스 점검(review) 판단 — 스키마, 요청 모양, 입력과 대조하는 검증(#1326, 결정 #1237 4절)."""

import json
import random
from functools import partial

import pytest
from openai.lib._pydantic import to_strict_json_schema

from llm import api as llm_api
from llm import client as llm_client
from llm import service
from llm.prompts import COURSE_DIRECT_PROMPT
from llm.schemas import (
    COURSE_REVIEW_FIX_REASONS, COURSE_REVIEW_KEEP_REASONS, COURSE_REVIEW_PICK_REASONS, CourseDirectTurn, CourseReviewCall,
)
from llm.tests.test_course_goals_direct import FakeClient

OPT = lambda no, moved, solves=(), remaining=(): {"no": no, "moved": moved, "solves": list(solves), "remaining": list(remaining)}  # noqa: E731
REVIEW = {"problems": [
    {"alias": "q1", "kind": "closed", "strength": "hard", "options": [OPT(1, 1, ["q1"])]},
    {"alias": "q2", "kind": "travel", "strength": "hard", "options": []},                              # 크게 바꿔야 해요
    {"alias": "q3", "kind": "goal", "strength": "soft", "options": [OPT(1, 1, ["q3"])]},
    {"alias": "q4", "kind": "condition", "strength": "soft", "options": [OPT(1, 1, ["q4"], ["q5"]), OPT(2, 2, ["q4", "q5"])]},
    {"alias": "q5", "kind": "meal", "strength": "soft", "options": [OPT(1, 3, ["q5"], ["q6"])]},
    {"alias": "q6", "kind": "cluster", "strength": "soft", "options": [OPT(1, 2, ["q6"], ["q3"])]},
    {"alias": "q7", "kind": "cluster", "strength": "soft", "options": []},
]}
INPUT = {"turn": 1, "goals": [], "candidates": [], "review": REVIEW, "budget": {"turns_left": 5}}


def call(order=(), verdicts=(), picks=()):
    return CourseReviewCall.model_validate({"tool": "review", "order": list(order), "picks": [
        {"problem": p, "option": o, "reason": r} for p, o, r in picks], "verdicts": [
        {"problem": p, "worth": w, "reason": r} for p, w, r in verdicts]})


def decide(**kw):
    return llm_api.verify_course_review(REVIEW, call(**kw))


class TestSchema:
    def test_strict_schema_has_no_oneof(self):
        assert "oneOf" not in json.dumps(to_strict_json_schema(CourseDirectTurn))

    def test_review_is_a_direct_action(self):
        turn = CourseDirectTurn.model_validate({"thought": "점검해요", "action": {
            "tool": "review", "order": ["q4"], "verdicts": [{"problem": "q4", "worth": "fix", "reason": "SMALL_CHANGE"}],
            "picks": [{"problem": "q4", "option": 2, "reason": "SOLVES_MORE"}]}})
        assert isinstance(turn.action, CourseReviewCall) and turn.action.order == ["q4"]

    @pytest.mark.parametrize("bad", [
        {"tool": "review", "order": [], "verdicts": [{"problem": "q3", "worth": "fix", "reason": "내가 지은 문장"}], "picks": []},   # 이유는 고정 목록
        {"tool": "review", "order": [], "verdicts": [{"problem": "q3", "worth": "later", "reason": "SMALL_CHANGE"}], "picks": []},
        {"tool": "review", "order": [], "verdicts": [], "picks": [], "message": "그대로 둬요"},                                      # 문장 칸이 없다
    ])
    def test_rejects_free_text_and_unknown_values(self, bad):
        with pytest.raises(ValueError):
            CourseDirectTurn.model_validate({"thought": "x", "action": bad})

    def test_reason_groups_cover_the_literal(self):
        assert len({*COURSE_REVIEW_FIX_REASONS, *COURSE_REVIEW_KEEP_REASONS, *COURSE_REVIEW_PICK_REASONS}) == 9


class TestCallShape:
    def test_review_rides_a_direct_turn_without_new_call(self):
        turn = CourseDirectTurn.model_validate({"thought": "t", "action": {"tool": "review", "order": [], "verdicts": [], "picks": []}})
        client = FakeClient(turn)
        reply = service.course_direct_turn(INPUT, planner=partial(llm_client.call_course_direct, client, turn=1))
        assert isinstance(reply.result.action, CourseReviewCall)
        assert json.loads(client.kwargs["messages"][1]["content"])["review"] == REVIEW         # 별칭만 — 이름·좌표·id가 없다
        assert client.kwargs["response_format"] is CourseDirectTurn and "tools" not in client.kwargs

    def test_prompt_describes_review_mode(self):
        for word in ("점검 모드", "review 도구를 한 번", "FIXES_REQUEST", "TOO_MANY_MOVES", "FEWER_MOVES", "hard 문제는 판단하지 않는다", "문장을 짓지 않는다"):
            assert word in COURSE_DIRECT_PROMPT


class TestVerify:
    def test_valid_judgement_passes_through(self):
        d = decide(order=["q5", "q4", "q3"], verdicts=[("q3", "fix", "FIXES_REQUEST"), ("q4", "fix", "FIXES_MEMBER_NEED"),
                                                       ("q5", "keep", "TOO_MANY_MOVES"), ("q6", "keep", "LEAVES_PROBLEMS")],
                   picks=[("q4", 2, "SOLVES_MORE")])
        assert d.order == ("q5", "q4", "q3")
        assert d.worth == {"q3": ("fix", "FIXES_REQUEST"), "q4": ("fix", "FIXES_MEMBER_NEED"), "q5": ("keep", "TOO_MANY_MOVES"), "q6": ("keep", "LEAVES_PROBLEMS")}
        assert d.picks == {"q4": (2, "SOLVES_MORE")}

    def test_hard_problems_and_unknown_aliases_are_ignored(self):
        d = decide(order=["q1", "q2", "q4", "zz", "p1"], verdicts=[("q1", "keep", "MINOR_GAIN"), ("q2", "keep", "MINOR_GAIN"), ("zz", "fix", "SMALL_CHANGE")],
                   picks=[("q1", 1, "FEWER_MOVES")])
        assert d.order == ("q4",) and d.worth == {} and d.picks == {}

    def test_problem_without_option_has_nothing_to_judge(self):
        assert decide(order=["q7"], verdicts=[("q7", "keep", "MINOR_GAIN")]).worth == {}

    def test_reason_must_match_the_judgement_and_the_input(self):
        d = decide(verdicts=[
            ("q3", "keep", "FIXES_REQUEST"),         # 판단 종류와 다른 코드
            ("q4", "fix", "FIXES_REQUEST"),          # q4는 goal이 아니라 condition
            ("q5", "keep", "LEAVES_PROBLEMS"),       # 맞다(남는 문제 q6)
            ("q6", "keep", "TOO_MANY_MOVES"),        # 맞다(2곳)
            ("q4", "keep", "MINOR_GAIN"),            # 둘째 판단이어도 첫 판단이 버려졌으니 받는다
        ])
        assert d.worth == {"q5": ("keep", "LEAVES_PROBLEMS"), "q6": ("keep", "TOO_MANY_MOVES"), "q4": ("keep", "MINOR_GAIN")}
        assert decide(verdicts=[("q4", "keep", "TOO_MANY_MOVES")]).worth == {}     # q4의 1안은 1곳만 옮긴다
        assert decide(verdicts=[("q4", "fix", "SMALL_CHANGE")]).worth == {}        # 모든 안에 남는 문제가 있거나 2곳이 아니다 → 1안은 q5가 남고 2안은 2곳
        assert decide(verdicts=[("q3", "fix", "SMALL_CHANGE")]).worth == {"q3": ("fix", "SMALL_CHANGE")}

    def test_first_judgement_wins(self):
        d = decide(order=["q4", "q3", "q4"], verdicts=[("q3", "fix", "FIXES_REQUEST"), ("q3", "keep", "MINOR_GAIN")])
        assert d.order == ("q4", "q3") and d.worth == {"q3": ("fix", "FIXES_REQUEST")}

    def test_pick_must_be_a_real_better_option(self):
        assert decide(picks=[("q4", 1, "FEWER_MOVES")]).picks == {"q4": (1, "FEWER_MOVES")}
        assert decide(picks=[("q4", 2, "FEWER_MOVES")]).picks == {}        # 2안이 더 많이 옮긴다
        assert decide(picks=[("q4", 1, "SOLVES_MORE")]).picks == {}        # 2안이 더 많이 푼다
        assert decide(picks=[("q4", 9, "FEWER_MOVES")]).picks == {}        # 없는 안 번호
        assert decide(picks=[("q4", 2, "FIXES_REQUEST")]).picks == {}      # 고르기 이유가 아니다
        assert decide(picks=[("q3", 1, "FEWER_MOVES")]).picks == {}        # 안이 하나뿐이면 고를 것이 없다

    def test_keep_drops_the_pick(self):
        assert decide(verdicts=[("q4", "keep", "MINOR_GAIN")], picks=[("q4", 2, "SOLVES_MORE")]).picks == {}

    def test_empty_output_is_the_code_default(self):
        assert decide() == llm_api.CourseReviewDecision((), {}, {})

    def test_hard_never_survives_any_output(self):
        """어떤 모델 출력에서도 하드 별칭은 순서·판단·안 고르기에 남지 않는다."""
        rng = random.Random(1326)
        aliases = [p["alias"] for p in REVIEW["problems"]] + ["zz"]
        reasons = [*COURSE_REVIEW_FIX_REASONS, *COURSE_REVIEW_KEEP_REASONS, *COURSE_REVIEW_PICK_REASONS]
        hard = {p["alias"] for p in REVIEW["problems"] if p["strength"] == "hard"}
        for _ in range(300):
            c = call(order=rng.sample(aliases, rng.randint(0, len(aliases))),
                     verdicts=[(rng.choice(aliases), rng.choice(["fix", "keep"]), rng.choice(reasons)) for _ in range(rng.randint(0, 8))],
                     picks=[(rng.choice(aliases), rng.randint(0, 3), rng.choice(reasons)) for _ in range(rng.randint(0, 4))])
            d = llm_api.verify_course_review(REVIEW, c)
            assert not hard & {*d.order, *d.worth, *d.picks}
            for alias, (worth, reason) in d.worth.items():       # 남은 판단은 입력과 모순되지 않는다
                assert reason in (COURSE_REVIEW_FIX_REASONS if worth == "fix" else COURSE_REVIEW_KEEP_REASONS)

    def test_failed_call_is_not_an_exception(self):
        reply = service.course_direct_turn(INPUT, planner=partial(llm_client.call_course_direct, FakeClient(RuntimeError("net")), turn=1))
        assert reply.result.reason == "call_failed" or reply.result.reason


def test_public_api():
    assert llm_api.verify_course_review is service.verify_course_review
    assert llm_api.CourseReviewCall is CourseReviewCall
