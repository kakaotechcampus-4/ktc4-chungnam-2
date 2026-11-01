"""개입 적절성 라벨링 표본(agent/label_sample.py, #1072).

실제 관찰(observe_map)로 제안을 만들고 CSV로 내보낸 뒤, 구성원이 쓴 글(사유 원문, 인용한 앞부분, 실시간 핀 검색어)과
구성원 id가 CSV 어디에도 없는지 본다(명세 2절 11, 13번). 인용 자리는 자리 표시로 남는다.
"""

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent import label_sample, tools
from agent.models import AgentRun, AgentSuggestion
from agent.tests.test_flows_model import AGAINST_TEXT, LIKE_TEXT, FakeGateway, _split_map, good_split, observe
from agent.tests.world import World, fake_places, real_now
from places import api as places_api

LIVE_QUERY = "망원동비밀검색어국수"


@pytest.fixture()
def world(factory, monkeypatch):
    monkeypatch.setattr(places_api, "get_places", fake_places({}))
    tools.STRUCTURE_CACHE.clear()
    w = World(factory, real_now())
    yield w
    w.cleanup()


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_export_masks_member_text_and_keeps_agent_words(world, factory, tmp_path):
    split_map, _, _, _ = _split_map(world)
    assert observe(world, split_map, FakeGateway(diagnose=good_split)) == "suggested"
    unseen_map, _ = world.unseen_map(("db", "pl_a"), ("live", LIVE_QUERY), ("db", "pl_b"))
    world.event(unseen_map)
    assert observe(world, unseen_map, FakeGateway()) == "suggested"
    gap_map = world.gap_map()
    world.event(gap_map)
    assert observe(world, gap_map, FakeGateway()) == "suggested"
    out = tmp_path / "labels.csv"

    with factory() as db:
        counts = label_sample.export(db, out, per_type=10, seed=0)

    assert counts == {"stall": 0, "split": 1, "no_reaction": 1, "category_gap": 1}
    raw = out.read_text(encoding="utf-8-sig")
    for secret in (AGAINST_TEXT, AGAINST_TEXT[:8], LIKE_TEXT, LIVE_QUERY, world.prefix):
        assert secret not in raw
    rows = {r["diagnosis"]: r for r in _read(out)}
    assert list(rows["split"]) == list(label_sample.HEADER)
    split = rows["split"]
    sug = world.one(AgentSuggestion, map_id=split_map)
    assert split["run_id"] == str(sug.run_id) and split["category"] == "음식점"
    assert split["제안 문장"].splitlines() == [
        "의견이 갈린 핀이 있어요",
        "- ♥ 2명, 🚫 1명으로 갈렸어요",
        "- 🚫 쪽은 「[인용]」라고 했어요",
    ]
    assert split["버튼"] == "음식점 추천 받기"
    assert (split["개입할 만했나"], split["메모"]) == ("", "")
    run = world.one(AgentRun, map_id=split_map, trigger="activity")
    [signal] = [s for s in run.signals if s["fingerprint"] == sug.fingerprint]
    assert json.loads(split["신호 특징값"]) == signal["features"]
    assert rows["no_reaction"]["제안 문장"].splitlines() == [
        "아직 확인되지 않은 핀이 3개 있어요", "- 「[핀]」", "- 「[핀]」", "- 「[핀]」"]
    assert rows["category_gap"]["버튼"] in ("카페 추천 받기 / 카페 핀 보기", "관광지 추천 받기 / 관광지 핀 보기")


def _sampled(diagnosis: str, i: int) -> label_sample.Sampled:
    return label_sample.Sampled(
        run_id=f"{diagnosis}-{i}", diagnosis=diagnosis, category=None,
        created_at=datetime(2026, 11, 1, tzinfo=timezone.utc) + timedelta(minutes=i),
        title="t", claims=[], advice=[], actions=[], features={},
    )


def test_pick_caps_each_type_and_is_repeatable():
    rows = [_sampled("stall", i) for i in range(10)] + [_sampled("split", i) for i in range(2)]

    first = label_sample.pick(rows, 3, seed=7)

    assert [r.diagnosis for r in first] == ["stall"] * 3 + ["split"] * 2
    assert first == label_sample.pick(list(reversed(rows)), 3, seed=7)
    stall = [r for r in first if r.diagnosis == "stall"]
    assert stall == sorted(stall, key=lambda r: r.created_at)


def test_quote_from_member_never_reaches_text_even_with_old_claims():
    """#717 전에 저장된 quote claim(범위 없음, text 칸이 남았을 수 있다)도 자리 표시만 나간다."""
    claims = [{"id": "c1", "kind": "quote", "reaction_id": "r1", "text": "여기로 정하자 비밀"}]
    advice = [{"slot_text": "반대 쪽은 {c1}라고 했어요", "is_guess": False}]

    text = label_sample.suggestion_text("의견이 갈린 핀이 있어요", claims, advice)

    assert "비밀" not in text and "「[인용]」" in text


def test_line_the_screen_would_drop_is_marked():
    advice = [{"slot_text": "지금 확정하세요", "is_guess": False}]   # 금지 표현(FORBIDDEN_PHRASES)

    assert label_sample.suggestion_text("제목", [], advice).splitlines() == ["제목", "- (렌더에서 빠짐)"]


@pytest.mark.parametrize("url, local", [
    ("postgresql://pingo:pw@localhost:5432/pingo", True),
    ("postgresql://pingo:pw@127.0.0.1/pingo", True),
    ("postgresql://pingo:pw@db.example.rds.amazonaws.com:5432/pingo", False),
    ("postgresql://pingo:pw@10.0.0.5/pingo", False),
])
def test_only_local_db(url, local):
    assert label_sample.is_local_db(url) is local


def test_refuses_csv_inside_repo(tmp_path):
    assert label_sample.inside_repo(label_sample.REPO_ROOT / "backend" / "labels.csv")
    assert not label_sample.inside_repo(tmp_path / "labels.csv")
