"""
사유 칩은 ②를 거치지 않는다(#412) — 칩 하나당 근거 줄 하나를 코드가 만들고(키·방향은 docs/constraints.md 칩 표),
②에는 사람이 쓴 글만 간다. HTTP로 반응 → run 생성 → 근거 → 실행 → 결과까지, 실제 장소 DB(PostGIS)에서.

전에는 칩을 label 글로 바꿔 ②에 넘겨서, 실제 모델이 「매워요」의 방향을 자주 비우거나(효과 없음) 칩 2개를
"매워요, 비싸요" 한 줄로 받아 둘 다 놓쳤다. 글과 칩을 함께 남기면 칩이 버려졌다(PR #411 코멘트).
"""

import pytest

from integration.real_places_fixtures import (  # noqa: F401 — 픽스처는 import로 등록된다
    PLACES, _pin, fake_planner, members, own_db, place_ids, real_client,
)


@pytest.fixture()
def planner_calls(fake_planner, monkeypatch):
    """fake_planner를 감싸 ②에 들어간 글을 기록한다."""
    import llm.service as llm_service

    calls: list[list[str]] = []

    def recording(raw_reasons):
        calls.append([r["text"] for r in raw_reasons])
        return fake_planner(raw_reasons)

    monkeypatch.setattr(llm_service, "get_evidence_planner", lambda: recording)
    return calls


def _run(client, map_id):
    run = client.post(f"/maps/{map_id}/runs", json={"category": "음식점"})
    assert run.status_code == 202, run.text
    return run.json()["id"]


def _chip_ids(db_session, run_id):
    from sqlalchemy import select

    from recommend.models import EvidenceLine as EvidenceLineRow

    db_session.expire_all()
    return set(db_session.execute(select(EvidenceLineRow.chip_id).where(EvidenceLineRow.run_id == run_id)).scalars())


def test_chips_and_text_become_one_line_each_and_only_text_goes_to_the_planner(members, place_ids, planner_calls, db_session):
    a, b, map_id = members
    pin = _pin(a, map_id, "K", place_ids)
    r = b.put(f"/pins/{pin}/reaction", json={
        "type": "against", "reason_text": "주차도 안 돼요", "reason_chip_ids": ["food_spicy", "food_cramped"]})
    assert r.status_code == 200, r.text

    run_id = _run(a, map_id)
    lines = a.get(f"/runs/{run_id}/evidence").json()

    assert planner_calls == [["주차도 안 돼요"]], "칩 label은 ②에 가지 않는다"
    assert len(lines) == 3, lines   # 글 1줄 + 칩 2줄(전에는 글 1줄만 남고 칩이 버려졌다)
    by_text = {line["text"]: line for line in lines}
    assert (by_text["매워요"]["fact_key"], by_text["매워요"]["wants"]) == ("spicy_focused", False)
    assert (by_text["좁아요"]["fact_key"], by_text["좁아요"]["wants"]) == ("spacious", True)
    assert all(line["badge"] == "required" for line in lines)
    # 어느 칩에서 왔는지는 DB에만 남는다(응답 EvidenceLine에는 chip_id가 없다)
    assert _chip_ids(db_session, run_id) == {"food_spicy", "food_cramped", None}


def test_chip_only_reaction_skips_the_planner_and_still_filters(members, place_ids, planner_calls):
    """칩만 남긴 🚫 — ② 호출 없이 칩 표의 방향(매워요 → spicy_focused, 피함)이 실제 결과에서 매운집을 뺀다."""
    a, b, map_id = members
    pin = _pin(a, map_id, "K", place_ids)
    assert b.put(f"/pins/{pin}/reaction", json={"type": "against", "reason_chip_ids": ["food_spicy"]}).status_code == 200

    run_id = _run(a, map_id)
    assert planner_calls == [], "글이 없으면 ②를 부르지 않는다"
    assert a.post(f"/runs/{run_id}/regions/confirm", json={}).status_code == 200
    assert a.post(f"/runs/{run_id}/execute").status_code == 202
    result = a.get(f"/runs/{run_id}/result")
    assert result.status_code == 200, result.text
    names = {c["place_name"] for c in result.json()["candidates"]}
    assert PLACES["S"][0] not in names, "매운맛 라벨이 참인 곳은 칩 「매워요」로 실격이다"
    assert names, "매운맛이 거짓이거나 모름(취향 조건)인 곳은 남는다"


def test_retired_shellfish_chip_is_rejected_for_new_reactions(members, place_ids):
    """「갑각류 알러지가 있어요」 칩은 #425에서 뺐다 — 새 반응에서는 고를 수 없다."""
    a, b, map_id = members
    pin = _pin(a, map_id, "K", place_ids)
    r = b.put(f"/pins/{pin}/reaction", json={"type": "against", "reason_chip_ids": ["food_shellfish"]})
    assert r.status_code == 422, r.text


def test_reaction_left_with_the_retired_chip_shows_its_label_without_a_condition(members, place_ids, planner_calls, db_session):
    """#425 전에 이 칩으로 남긴 반응 — 근거 줄에 id("food_shellfish")가 아니라 이름이 보이고, 조건(키)은 없다(거르지 않는다)."""
    from sqlalchemy import update

    from pins.models import Reaction

    a, b, map_id = members
    pin = _pin(a, map_id, "K", place_ids)
    assert b.put(f"/pins/{pin}/reaction", json={"type": "against", "reason_chip_ids": ["food_spicy"]}).status_code == 200
    db_session.execute(update(Reaction).where(Reaction.pin_id == pin).values(reason_chip_ids=["food_shellfish"]))   # 옛 데이터 흉내
    db_session.commit()

    run_id = _run(a, map_id)
    assert planner_calls == []
    [line] = a.get(f"/runs/{run_id}/evidence").json()
    assert (line["text"], line.get("fact_key"), line.get("wants")) == ("갑각류 알러지가 있어요", None, None)   # 값이 없는 필드는 응답에서 빠진다
