"""snapshot.build(#514) — 다른 모듈 api.py로만 읽고, 공개 데이터만 담는다(명세 12.7, 17절 1번).

17절 1번(가장 중요한 테스트): DB에 남의 run, 후보, run의 근거 줄, 제외 목록을 넣고 스냅샷 직렬화에 그 id와 글이
없는지 본다. 도구 결과와 diagnosis_input은 M1에서 같은 픽스처로 더한다.
"""

import dataclasses
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func

from agent import snapshot
from auth.models import User
from auth.testing import ensure_users
from maps.models import Map, Membership
from common.events import EventLog
from pins.models import Pin, Reaction
from recommend.models import Candidate, EvidenceLine, Exclusion, RecommendRun
from shortlist.models import ShortlistItem

T0 = datetime(2026, 10, 15, 0, 0, tzinfo=timezone.utc)
NOW = T0 + timedelta(hours=10)

SECRET_CANDIDATE_REASON = "비밀후보이유_조용한골목집"
SECRET_EVIDENCE_TEXT = "비밀근거줄_매운곳제외해줘"
SECRET_REQUESTER = "secret_requester"


def _map(db, *, deleted=False):
    row = Map(title="지도", start_date=date(2026, 11, 1), end_date=date(2026, 11, 3), created_by="u1",
              deleted_at=T0 if deleted else None)
    db.add(row)
    db.flush()
    ensure_users(db, "u1", "u2", "u3", SECRET_REQUESTER)
    for i, uid in enumerate(("u2", "u1", "u3")):
        db.add(Membership(map_id=row.id, user_id=uid, role="owner" if uid == "u1" else "member",
                          joined_at=T0 + timedelta(minutes=i)))
    db.flush()
    return row.id


def _pin(db, map_id, *, category="음식점", by="u1", minutes=0, deleted=False):
    row = Pin(
        id=uuid.uuid4(), map_id=map_id, category=category, kind="일반", origin="direct",
        place_id=f"place_{uuid.uuid4().hex[:8]}", geom=func.ST_SetSRID(func.ST_MakePoint(127.0, 37.5), 4326),
        visibility="public", created_by=by, created_at=T0 + timedelta(minutes=minutes),
        deleted_at=T0 + timedelta(hours=1) if deleted else None,
    )
    db.add(row)
    db.flush()
    return row


def _react(db, pin, user_id, type_, *, minutes, text=None, chips=None):
    row = Reaction(id=uuid.uuid4(), pin_id=pin.id, user_id=user_id, type=type_, reason_text=text,
                   reason_chip_ids=chips, updated_at=T0 + timedelta(minutes=minutes))
    db.add(row)
    db.flush()
    return row


def _private_run_data(db, map_id):
    """남의 run과 그 후보, 근거 줄, 제외 목록. 스냅샷에 하나도 들어가면 안 된다."""
    run = RecommendRun(map_id=map_id, category="음식점", requested_by=SECRET_REQUESTER, status="done",
                       created_at=T0 + timedelta(hours=2))
    db.add(run)
    db.flush()
    candidate = Candidate(run_id=run.id, place_id="secret_place_candidate", lat=37.5, lng=127.0, rank=1,
                          reason=SECRET_CANDIDATE_REASON)
    line = EvidenceLine(run_id=run.id, author_id=SECRET_REQUESTER, source="manual", text=SECRET_EVIDENCE_TEXT,
                        badge="required")
    exclusion = Exclusion(map_id=map_id, category="음식점", place_id="secret_place_excluded", reason="dismissed",
                          run_id=run.id, requested_by=SECRET_REQUESTER)
    db.add_all([candidate, line, exclusion])
    db.flush()
    return {
        "ids": [str(run.id), str(candidate.id), str(line.id), str(exclusion.id),
                "secret_place_candidate", "secret_place_excluded", SECRET_REQUESTER],
        "texts": [SECRET_CANDIDATE_REASON, SECRET_EVIDENCE_TEXT],
        "created_at": run.created_at,
    }


def _serialized(snap) -> str:
    return repr(dataclasses.asdict(snap))


def test_private_run_data_never_enters_snapshot(db_session):
    """17절 1번 — run, 후보, 근거 줄, 제외 목록의 id와 글이 스냅샷 어디에도 없다. run은 시각 하나로만 남는다."""
    map_id = _map(db_session)
    p = _pin(db_session, map_id)
    _react(db_session, p, "u2", "against", minutes=30, text="너무 시끄러워요")
    secret = _private_run_data(db_session, map_id)

    snap = snapshot.build(db_session, map_id, NOW)
    dumped = _serialized(snap)

    for value in secret["ids"] + secret["texts"]:
        assert value not in dumped
    assert snap.last_run_at == {"음식점": secret["created_at"]}
    assert snap.has_run_since("음식점", T0) is True
    assert snap.has_run_since("음식점", secret["created_at"]) is False


def test_members_get_aliases_in_join_order(db_session):
    map_id = _map(db_session)

    snap = snapshot.build(db_session, map_id, NOW)

    assert [(m.user_id, m.alias) for m in snap.members] == [("u2", "m1"), ("u1", "m2"), ("u3", "m3")]
    assert snap.member_count == 3


def test_withdrawn_member_is_not_in_members(db_session):
    map_id = _map(db_session)
    db_session.get(User, "u3").deleted_at = T0
    db_session.flush()

    snap = snapshot.build(db_session, map_id, NOW)

    assert [m.user_id for m in snap.members] == ["u2", "u1"]


def test_pins_reactions_shortlist_and_actions(db_session):
    map_id = _map(db_session)
    food = _pin(db_session, map_id, category="음식점", by="u1", minutes=0)
    cafe = _pin(db_session, map_id, category="카페", by="u2", minutes=10)
    gone = _pin(db_session, map_id, category="음식점", by="u3", minutes=20, deleted=True)
    like = _react(db_session, food, "u2", "like", minutes=30)
    _react(db_session, gone, "u1", "against", minutes=40, text="삭제된 핀의 사유")
    db_session.add(ShortlistItem(map_id=map_id, pin_id=cafe.id, added_by="u3", added_at=T0 + timedelta(minutes=50)))
    db_session.add(ShortlistItem(map_id=map_id, pin_id=gone.id, added_by="u3", added_at=T0 + timedelta(minutes=60)))
    db_session.flush()

    snap = snapshot.build(db_session, map_id, NOW)

    assert {p.pin_id for p in snap.pins} == {str(food.id), str(cafe.id)}           # 삭제된 핀 제외
    assert [r.reaction_id for r in snap.reactions] == [str(like.id)]
    assert [i.pin_id for i in snap.shortlist] == [str(cafe.id)]                    # 삭제된 핀의 확정 항목 제외
    assert snap.is_confirmed(str(cafe.id)) and not snap.is_confirmed(str(food.id))
    assert snap.has_reaction("u2", str(food.id)) and not snap.has_reaction("u1", str(food.id))
    assert [(a.kind, a.user_id, a.category) for a in snap.actions] == [
        ("pin", "u1", "음식점"), ("pin", "u2", "카페"), ("reaction", "u2", "음식점"), ("shortlist", "u3", "카페"),
    ]
    assert snap.action_times == sorted(snap.action_times)
    assert snap.latest_seq is None and snap.latest_event_at is None   # 이 지도 이벤트가 없다


def test_reasons_include_deleted_pins_with_alias_and_chips(db_session):
    """사유는 삭제된 핀의 것도 담는다(명세 8절, #243). 칩은 표의 키와 방향을 그대로 쓴다(#412)."""
    map_id = _map(db_session)
    alive = _pin(db_session, map_id, category="카페")
    gone = _pin(db_session, map_id, category="음식점", deleted=True)
    r1 = _react(db_session, alive, "u2", "like", minutes=5, text="조용해서 좋아요")
    r2 = _react(db_session, gone, "u3", "against", minutes=6, chips=["food_expensive"])
    _react(db_session, alive, "u1", "like", minutes=7)   # 사유 없는 ♥는 담지 않는다

    snap = snapshot.build(db_session, map_id, NOW)
    by_id = {r.reaction_id: r for r in snap.reasons}

    assert set(by_id) == {str(r1.id), str(r2.id)}
    assert (by_id[str(r1.id)].alias, by_id[str(r1.id)].text, by_id[str(r1.id)].pin_deleted) == ("m1", "조용해서 좋아요", False)
    assert by_id[str(r1.id)].category == "카페"
    assert by_id[str(r2.id)].pin_deleted is True
    assert [c.chip_id for c in by_id[str(r2.id)].chips] == ["food_expensive"]


def test_today_is_kst_date(db_session):
    map_id = _map(db_session)
    late_utc = datetime(2026, 10, 15, 15, 30, tzinfo=timezone.utc)   # KST 10/16 00:30

    assert snapshot.build(db_session, map_id, late_utc).today == date(2026, 10, 16)


def test_deleted_map_has_only_map_info(db_session):
    map_id = _map(db_session, deleted=True)

    snap = snapshot.build(db_session, map_id, NOW)

    assert snap.map.deleted is True
    assert (snap.members, snap.pins, snap.reasons) == ((), (), ())


def test_missing_map_is_none(db_session):
    assert snapshot.build(db_session, "no_such_map", NOW) is None


def test_latest_seq_is_this_maps_largest_event(db_session):
    """커서용 — 이 지도의 가장 큰 event_log seq와 그 시각(12.5). 다른 지도 이벤트는 보지 않는다."""
    map_id, other = _map(db_session), _map(db_session)
    rows = [EventLog(map_id=m, channel="public", type="pin.created", payload={}) for m in (map_id, map_id, other)]
    db_session.add_all(rows)
    db_session.flush()

    snap = snapshot.build(db_session, map_id, NOW)

    assert snap.latest_seq == rows[1].seq
    assert snap.latest_event_at == rows[1].created_at
