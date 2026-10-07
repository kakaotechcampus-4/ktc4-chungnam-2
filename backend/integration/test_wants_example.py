"""#231 — docs/constraints.md "사유의 방향(wants)과 실격"의 가·나·다 세 사람 예시를 그대로 돌린다.

가: 🚫 "한식 말고"      cuisine_korean, required, wants=false
나: 「+」 "회 좋아해"     cuisine_raw_fish, preferred, wants=true
다: 🚫 "너무 매워요"     spicy_focused, required, wants=false (취향 키, #378)
②(llm)의 wants 생성은 별도 이슈라 근거 줄을 직접 심는다.
"""

from authz.core import Principal
from recommend import flows, service
from recommend.ports import PlaceStub
from recommend.tests.test_flows import _FakePlaceFacts, _FakePlaceSearch, _make_members, _make_region, _make_run

FACTS = {
    "korean_true": {"cuisine_korean": True, "spicy_focused": False},      # 한식집 → 실격(가)
    "korean_unknown": {"spicy_focused": False},                          # 한식 라벨 모름 → 통과 + 확인 필요
    "raw_fish": {"cuisine_korean": False, "cuisine_raw_fish": True, "spicy_focused": False},  # 횟집 → +1점
    "spicy_true": {"cuisine_korean": False, "spicy_focused": True},      # 매운맛 전문 → 실격(다)
    "spicy_unknown": {"cuisine_korean": False},                          # 매운맛 모름 → 통과 + 확인 필요(다, 취향 키)
}


def test_three_person_example_from_the_constraints_doc(db_session):
    run = _make_run(db_session, status="collecting_evidence")
    _make_members(db_session, user_ids=["user_1", "user_2", "user_3"])
    _make_region(db_session, run, radius_m=1000)
    service.add_reaction_evidence(db_session, run_id=run.id, lines=[
        {"author_id": "user_1", "source": "reaction", "text": "한식 말고 다른 거", "badge": "required",
         "fact_key": "cuisine_korean", "wants": False},
        {"author_id": "user_2", "source": "reaction", "text": "회 좋아해", "badge": "preferred",
         "fact_key": "cuisine_raw_fish", "wants": True},
        {"author_id": "user_3", "source": "reaction", "text": "너무 매워요", "badge": "required",
         "fact_key": "spicy_focused", "wants": False},
    ])
    places = [PlaceStub(place_id=pid, lat=35.0005, lng=129.0005) for pid in FACTS]
    search = _FakePlaceSearch(places)

    flows.execute_run(db_session, run_id=str(run.id), place_search=search, place_facts=_FakePlaceFacts(FACTS))

    candidates = {c.place_id: c for c in service.list_candidates(db_session, str(run.id))}
    assert set(candidates) == {"korean_unknown", "raw_fish", "spicy_unknown"}   # 한식집·매운맛 전문(참)만 실격
    assert candidates["raw_fish"].rank == 1                               # 횟집은 +1점으로 위로
    korean_check = next(c for c in candidates["korean_unknown"].checks if c["fact_key"] == "cuisine_korean")
    assert korean_check["needs_check"] is True and korean_check["passed"] is True
    spicy_check = next(c for c in candidates["spicy_unknown"].checks if c["fact_key"] == "spicy_focused")
    assert spicy_check["needs_check"] is True and spicy_check["passed"] is True   # 모름은 통과 + 확인 필요
    assert {e["label"]: e["removed_count"] for e in run.last_funnel}["실격 조건 제거"] == 2

    principal = Principal(user_id="user_1", map_id=run.map_id, role="member")
    result = flows.get_result(db_session, run_id=str(run.id), principal=principal, place_search=search)
    assert result.candidates[0].place_name == "이름-raw_fish"   # 횟집이 1순위로 응답에 나간다
    evidence = {e.fact_key: e for e in flows.list_evidence(db_session, run_id=str(run.id), principal=principal)}
    assert evidence["cuisine_korean"].wants is False and evidence["cuisine_korean"].fact_label == "한식"
