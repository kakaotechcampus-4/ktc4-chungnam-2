"""feedback.service·api — 공백 정리·길이, 저장, 익명화. 탈퇴 전체 흐름은 auth/tests/test_service.py가 본다."""

import pytest
from common.errors import AppError
from feedback import api, service
from feedback.models import Feedback


def _submit(db, user_id="u1", message="좋아요", category="other", map_id=None):
    return service.submit(db, user_id=user_id, message=message, category=category, map_id=map_id)


def test_message_is_stripped_before_saving(db_session):
    row = _submit(db_session, message="  버그예요\n ")
    assert row.message == "버그예요" and row.created_at is not None


@pytest.mark.parametrize("message", ["", "   \n\t", "a" * 1001, " " + "a" * 1001])
def test_empty_or_too_long_message_is_rejected(db_session, message):
    with pytest.raises(AppError) as exc:
        _submit(db_session, message=message)
    assert exc.value.code == "VALIDATION_ERROR"


def test_thousand_chars_after_strip_is_accepted(db_session):
    assert len(_submit(db_session, message=" " + "가" * 1000 + " ").message) == 1000


def test_map_id_is_saved_without_checking_it(db_session):
    assert _submit(db_session, map_id="no-such-map").map_id == "no-such-map"


def test_anonymize_by_user_nulls_only_that_users_rows_and_keeps_content(db_session):
    mine = _submit(db_session, user_id="leaver", message="내 의견", map_id="m1")
    other = _submit(db_session, user_id="stayer")

    assert api.anonymize_by_user(db_session, user_id="leaver") == 1

    db_session.expire_all()
    assert db_session.get(Feedback, mine.id).user_id is None
    assert db_session.get(Feedback, mine.id).message == "내 의견"
    assert db_session.get(Feedback, other.id).user_id == "stayer"

