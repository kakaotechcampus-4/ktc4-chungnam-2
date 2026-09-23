from auth import api, service
from auth.models import User


def test_display_names_returns_empty_dict_for_empty_input(db_session):
    assert api.display_names(db_session, []) == {}


def test_display_names_batches_lookup_for_multiple_users(db_session):
    db_session.add(User(id="user_1", provider="kakao", provider_user_id="pu1", display_name="철수"))
    db_session.add(User(id="user_2", provider="kakao", provider_user_id="pu2", display_name="영희"))
    db_session.flush()

    result = api.display_names(db_session, ["user_1", "user_2", "no-such-user"])

    assert result == {"user_1": "철수", "user_2": "영희"}


def test_display_names_still_returns_withdrawn_users(db_session):
    """탈퇴한 사용자도 이름은 보여준다 — 과거 반응·핀 작성자 표시가 사라지면 안 된다."""
    db_session.add(User(id="user_1", provider="kakao", provider_user_id="pu1", display_name="철수"))
    db_session.flush()
    service.withdraw_user(db_session, user_id="user_1")

    result = api.display_names(db_session, ["user_1"])

    assert result == {"user_1": "철수"}
