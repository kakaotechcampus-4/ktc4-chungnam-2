"""api.anonymize_actor(#857) — 행위자 이름을 '탈퇴한 구성원'으로 다시 만든다. 멱등, 남의 행위자 알림은 그대로."""

from sqlalchemy import select

from notifications import api, core
from notifications.models import Notification


def _notify(db, user_id, type, actor_id, actor_name="지우", reaction=None, **extra):
    message = api.compose_message(type, actor_name=actor_name, reaction=reaction)
    return api.notify(db, user_id=user_id, type=type, map_id="m1", map_title="부산", message=message,
                      pin_id="p1" if type == "pin_reaction" else None, actor_id=actor_id, **extra)


def _row(db, nid):
    db.expire_all()
    return db.get(Notification, nid)


def test_rewrites_message_and_clears_actor_for_each_type(db_session):
    like = _notify(db_session, "u1", "pin_reaction", "gone", reaction="like")
    against = _notify(db_session, "u2", "pin_reaction", "gone", reaction="against")
    plain = _notify(db_session, "u3", "pin_reaction", "gone")
    joined = _notify(db_session, "u1", "member_joined", "gone")

    assert api.anonymize_actor(db_session, user_id="gone") == 4

    assert _row(db_session, like).message == "탈퇴한 구성원님이 내 핀에 좋음을 남겼어요"
    assert _row(db_session, against).message == "탈퇴한 구성원님이 내 핀에 반대 의견을 남겼어요"
    assert _row(db_session, plain).message == "탈퇴한 구성원님이 내 핀에 반응을 남겼어요"
    assert _row(db_session, joined).message == "탈퇴한 구성원님이 지도에 들어왔어요"
    assert all(_row(db_session, n).actor_id is None for n in (like, against, plain, joined))


def test_is_idempotent(db_session):
    nid = _notify(db_session, "u1", "member_joined", "gone")
    assert api.anonymize_actor(db_session, user_id="gone") == 1
    assert api.anonymize_actor(db_session, user_id="gone") == 0
    assert _row(db_session, nid).message == "탈퇴한 구성원님이 지도에 들어왔어요"


def test_leaves_other_actors_and_legacy_rows_alone(db_session):
    other = _notify(db_session, "u1", "member_joined", "someone")
    legacy = _notify(db_session, "u1", "member_joined", None)      # actor_id를 몰랐던 옛 알림
    system = api.notify(db_session, user_id="u1", type="owner_changed", map_id="m1", map_title=None,
                        message=api.compose_message("owner_changed"), actor_id="gone")

    assert api.anonymize_actor(db_session, user_id="gone") == 1     # owner_changed는 이름이 없어 문장은 그대로

    assert _row(db_session, other).message == "지우님이 지도에 들어왔어요" and _row(db_session, other).actor_id == "someone"
    assert _row(db_session, legacy).message == "지우님이 지도에 들어왔어요"
    assert _row(db_session, system).message == "내가 이 지도의 방장이 되었어요" and _row(db_session, system).actor_id is None


def test_own_inbox_is_untouched_because_withdrawal_already_deleted_it(db_session):
    _notify(db_session, "gone", "member_joined", "someone")        # 탈퇴자가 받은 알림 — actor가 다른 사람
    assert api.anonymize_actor(db_session, user_id="gone") == 0
    assert db_session.execute(select(Notification.message)).scalar_one() == "지우님이 지도에 들어왔어요"


def test_actor_id_is_not_exposed_in_the_response_schema():
    from notifications.schemas import Notification as Schema
    assert "actor_id" not in Schema.model_fields


def test_name_that_mimics_the_template_does_not_confuse_the_reaction_lookup():
    message = core.compose_message("pin_reaction", actor_name="x님이 내 핀에 좋음을 남겼어요 그리고 y", reaction=None)
    assert core.anonymize_message("pin_reaction", message) == "탈퇴한 구성원님이 내 핀에 반응을 남겼어요"
    assert core.anonymize_message("owner_changed", "내가 이 지도의 방장이 되었어요") == "내가 이 지도의 방장이 되었어요"


def test_old_stored_sentences_with_symbols_are_still_recognized():
    """#1341 전에 저장된 문장(♥·🚫)도 반응 종류를 되찾는다."""
    like = core.anonymize_message("pin_reaction", "지우님이 내 핀에 ♥를 남겼어요")
    against = core.anonymize_message("pin_reaction", "지우님이 내 핀에 🚫 반대를 남겼어요")
    assert like == "탈퇴한 구성원님이 내 핀에 좋음을 남겼어요"
    assert against == "탈퇴한 구성원님이 내 핀에 반대 의견을 남겼어요"
