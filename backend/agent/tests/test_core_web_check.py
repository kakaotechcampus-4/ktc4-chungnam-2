"""웹 확인의 순수 함수(명세 6.8, #1216) — 대상 고르기, 24시간 재사용, 저장 모양, 렌더, 금지 표현 목록."""

from datetime import datetime, timedelta, timezone

from agent import core
from llm import api as llm_api

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
URL = "https://blog.example.com/1"


def _web(status="found", *, hours_ago=1, statements=None):
    if statements is None:
        statements = [{"text": "주차된다고 적혀 있어요", "source_url": URL}] if status == "found" else []
    return {"status": status, "statements": statements, "checked_at": (NOW - timedelta(hours=hours_ago)).isoformat()}


# ---------------------------------------------------------------- 대상

def test_targets_are_every_unknown_line():
    """「모름」인 줄 모두(#1317). 줄은 많아야 FACT_LINES_MAX(2)라 웹 확인도 많아야 2번이다."""
    facts = [{"pin_id": "p1", "fact_key": "quiet"}, {"pin_id": "p1", "fact_key": "parking_available"}]
    assert core.web_check_targets(facts, {"p1": {}}) == [0, 1]                          # 둘 다 모름
    assert core.web_check_targets(facts, {"p1": {"quiet": True}}) == [1]                # 참은 건너뛴다
    assert core.web_check_targets(facts, {"p1": {"quiet": None, "parking_available": True}}) == [0]
    assert core.web_check_targets(facts, {"p1": {"quiet": False, "parking_available": False}}) == []
    assert core.web_check_targets(facts, {}) == []                                      # 자체 DB 장소가 아닌 핀(값을 못 읽음)
    third = facts + [{"pin_id": "p1", "fact_key": "spacious"}]
    assert core.web_check_targets(third, {"p1": {}}) == [0, 1]                          # 상한 밖 줄은 보지 않는다


# ---------------------------------------------------------------- 24시간 재사용

def test_reuse_takes_the_latest_found_or_not_found_within_24_hours():
    older, newer = _web("found", hours_ago=10), _web("not_found", hours_ago=3)
    earlier = [[{"pin_id": "p1", "fact_key": "quiet", "web": older}], [{"pin_id": "p1", "fact_key": "quiet", "web": newer}]]
    assert core.reusable_web(earlier, "p1", "quiet", NOW) == newer


def test_reuse_skips_paused_old_other_keys_and_broken_rows():
    earlier = [[
        {"pin_id": "p1", "fact_key": "quiet", "web": _web("paused")},
        {"pin_id": "p1", "fact_key": "quiet", "web": _web("found", hours_ago=25)},
        {"pin_id": "p2", "fact_key": "quiet", "web": _web("found")},
        {"pin_id": "p1", "fact_key": "parking_available", "web": _web("found")},
        {"pin_id": "p1", "fact_key": "quiet", "web": {"status": "found", "checked_at": "어제"}},
        {"pin_id": "p1", "fact_key": "quiet"},
    ]]
    assert core.reusable_web(earlier, "p1", "quiet", NOW) is None


# ---------------------------------------------------------------- 저장 모양

def test_record_keeps_text_and_url_only_and_drops_failed():
    found = llm_api.VerifiedStatement(text="주차된다고 적혀 있어요", source_url=URL, source_name="blog.example.com")
    assert core.web_record("found", (found,), NOW) == {
        "status": "found", "statements": [{"text": "주차된다고 적혀 있어요", "source_url": URL}], "checked_at": NOW.isoformat()}
    assert core.web_record("paused", (), NOW)["statements"] == []
    assert core.web_record("failed", (), NOW) is None


# ---------------------------------------------------------------- 렌더

def test_render_adds_notice_and_source_name():
    rendered = core.render_web(_web("found"), llm_api.source_name)
    assert rendered.notice is None and rendered.statements[0].source_name == "blog.example.com"
    assert core.render_web(_web("not_found"), llm_api.source_name).notice == core.WEB_NOTICES["not_found"]
    assert core.render_web(_web("paused"), llm_api.source_name).notice == core.WEB_NOTICES["paused"]


def test_render_drops_broken_or_unsafe_rows():
    unsafe = _web("found", statements=[{"text": "누르세요", "source_url": "javascript:alert(1)"}])
    assert core.render_web(unsafe, llm_api.source_name) is None
    assert core.render_web({"status": "failed", "statements": [], "checked_at": NOW.isoformat()}, llm_api.source_name) is None
    assert core.render_web(_web("found"), None) is None
    assert core.render_web(None, llm_api.source_name) is None


def test_fact_line_without_web_has_no_web_key():
    refs = core.RenderRefs(pin_names={"p1": "성수 칼국수"}, fact_labels={"quiet": "조용함"}, fact_values={"p1": {}},
                           source_name=llm_api.source_name)
    [plain] = core.render_fact_lines([{"pin_id": "p1", "fact_key": "quiet"}], refs)
    assert "web" not in plain.model_dump(mode="json")
    [checked] = core.render_fact_lines([{"pin_id": "p1", "fact_key": "quiet", "web": _web("not_found")}], refs)
    assert checked.model_dump(mode="json")["web"]["notice"] == "웹에서도 찾지 못했어요"


# ---------------------------------------------------------------- 금지 표현은 한 곳

def test_forbidden_list_extends_the_diagnosis_list():
    assert set(core.FORBIDDEN_PHRASES) <= set(core.WEB_CHECK_FORBIDDEN)
    assert {"괜찮아요", "가보세요", "추천해요"} <= set(core.WEB_CHECK_FORBIDDEN)
