from auth import api, service
from auth.testing import create_guest, create_kakao_user


def test_display_names_returns_empty_dict_for_empty_input(db_session):
    assert api.display_names(db_session, []) == {}


def test_display_names_batches_lookup_for_multiple_users(db_session):
    create_kakao_user(db_session, "user_1", display_name="철수")
    create_kakao_user(db_session, "user_2", display_name="영희")

    result = api.display_names(db_session, ["user_1", "user_2", "no-such-user"])

    assert result == {"user_1": "철수", "user_2": "영희"}


def test_display_names_masks_withdrawn_users(db_session):
    """탈퇴한 사용자는 "탈퇴한 구성원"으로 내려간다 — 남는 핀 작성자 표시는 유지하되 실명은 숨긴다."""
    create_kakao_user(db_session, "user_1", display_name="철수")
    service.withdraw_user(db_session, user_id="user_1")

    result = api.display_names(db_session, ["user_1"])

    assert result == {"user_1": "탈퇴한 구성원"}


def test_guest_user_ids_picks_only_guests_in_one_batch(db_session):
    create_kakao_user(db_session, "k1", display_name="철수")
    create_guest(db_session, "g1", display_name="손님")

    assert api.guest_user_ids(db_session, ["k1", "g1", "no-such-user"]) == {"g1"}
    assert api.guest_user_ids(db_session, []) == set()
