"""후기 엔드포인트 4개 — main.app을 그대로 태운다(docs/credits-reviews.md 12절 17~24). 인증은 서명된 세션 쿠키.

정책 값은 reviews/constants.py, 보상·처음 지급량은 credits.api(get_balance)와 credits/constants.py에서 읽는다(숫자를 다시 적지 않는다).
"""

import uuid
from decimal import ROUND_HALF_UP, Decimal

import pytest
from sqlalchemy import func, select

from credits import api as credits_api
from credits.constants import INITIAL_CREDITS, MAX_BALANCE, REVIEW_REWARD
from credits.models import CreditAccount, CreditLedger
from maps.models import Membership
from pins.models import Pin
from reviews.constants import PAGE_SIZE, RATING_MAX, RATING_MIN, REVIEW_BODY_MAX
from reviews.models import Review, ReviewReport
from reviews.scripts.hide import set_hidden


@pytest.fixture()
def trip(world):
    """지도 하나(a 방장, b 구성원), 자체 DB 장소 핀 하나."""
    a, b = world.user("a"), world.user("b")
    map_id = world.map(a, b)
    place_id = world.place()
    pin_id = world.pin(map_id, place_id, by=a)
    return {"a": a, "b": b, "map_id": map_id, "place_id": place_id, "pin_id": pin_id}


def _count(db, model, *where) -> int:
    return db.execute(select(func.count()).select_from(model).where(*where)).scalar_one()


def _put(client, pin_id, rating=5, body="또 가고 싶어요"):
    return client.put(f"/pins/{pin_id}/reviews/me", json={"rating": rating, "body": body})


# 로그인 -----------------------------------------------------------------------------------------------------------

def test_every_route_requires_login(app_client, trip):
    pin_id = trip["pin_id"]
    assert app_client.get(f"/pins/{pin_id}/reviews").status_code == 401
    assert app_client.put(f"/pins/{pin_id}/reviews/me", json={"rating": 5, "body": "x"}).status_code == 401
    assert app_client.delete(f"/pins/{pin_id}/reviews/me").status_code == 401
    assert app_client.post(f"/reviews/{uuid.uuid4()}/reports").status_code == 401


# 17 ---------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("payload", [
    {"rating": RATING_MIN - 1, "body": "좋아요"},
    {"rating": RATING_MAX + 1, "body": "좋아요"},
    {"rating": 4.5, "body": "좋아요"},
    {"rating": "4", "body": "좋아요"},
    {"rating": True, "body": "좋아요"},
    {"rating": 4, "body": "   \n\t "},
    {"rating": 4, "body": "가" * (REVIEW_BODY_MAX + 1)},
    {"rating": 4},
    {"body": "좋아요"},
])
def test_invalid_rating_or_body_is_422_and_writes_nothing(world, trip, payload):
    r = world.client(trip["a"]).put(f"/pins/{trip['pin_id']}/reviews/me", json=payload)

    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"
    assert _count(world.db, Review, Review.place_id == trip["place_id"]) == 0


def test_body_at_max_length_is_saved_trimmed(world, trip):
    body = "가" * REVIEW_BODY_MAX
    r = _put(world.client(trip["a"]), trip["pin_id"], body=f"  {body}\n")

    assert r.status_code == 200
    assert r.json()["review"]["body"] == body


# 18 ---------------------------------------------------------------------------------------------------------------

def _spend_to(db, user_id, target: int) -> int:
    """잔액이 target 이하가 될 때까지 코스를 차감한다 — 보상이 잔액 상한(#981)에 걸리지 않게. 남은 잔액."""
    balance = credits_api.get_balance(db, user_id=user_id)
    while balance > target:
        balance = credits_api.charge(db, user_id=user_id, feature="course", run_id=str(uuid.uuid4()))
    return balance


def test_first_save_credits_reward_then_edit_and_rewrite_credit_nothing(world, trip):
    a = world.client(trip["a"])
    before = _spend_to(world.db, trip["a"], MAX_BALANCE - REVIEW_REWARD)

    first = _put(a, trip["pin_id"], rating=5, body="처음")
    edited = _put(a, trip["pin_id"], rating=2, body="다시 가 보니 별로")
    assert a.delete(f"/pins/{trip['pin_id']}/reviews/me").status_code == 204
    rewritten = _put(a, trip["pin_id"], rating=3, body="세 번째")

    assert first.status_code == edited.status_code == rewritten.status_code == 200
    assert [r.json()["credited"] for r in (first, edited, rewritten)] == [REVIEW_REWARD, 0, 0]
    assert first.json()["balance"] == before + REVIEW_REWARD
    assert rewritten.json()["balance"] == first.json()["balance"]
    assert edited.json()["review"]["id"] == first.json()["review"]["id"]
    assert (edited.json()["review"]["rating"], edited.json()["review"]["body"]) == (2, "다시 가 보니 별로")
    assert edited.json()["review"]["created_at"] == first.json()["review"]["created_at"]
    reasons = world.db.execute(select(CreditLedger.reason).where(CreditLedger.user_id == trip["a"])).scalars().all()
    assert sorted(r for r in reasons if r != "spend") == ["initial", "review"]


def test_balance_follows_existing_ledger(world, trip):
    credits_api.charge(world.db, user_id=trip["a"], feature="course", run_id=str(uuid.uuid4()))
    before = credits_api.get_balance(world.db, user_id=trip["a"])

    r = _put(world.client(trip["a"]), trip["pin_id"])

    assert r.json()["balance"] == before + r.json()["credited"] == min(before + REVIEW_REWARD, MAX_BALANCE)   # 상한(#981)


def test_delete_without_my_review_is_404(world, trip):
    world.review(trip["place_id"], trip["b"])   # 남의 후기는 지우지 않는다

    r = world.client(trip["a"]).delete(f"/pins/{trip['pin_id']}/reviews/me")

    assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"
    assert _count(world.db, Review, Review.place_id == trip["place_id"]) == 1


# 19 ---------------------------------------------------------------------------------------------------------------

def test_live_pin_is_422_place_not_supported_on_every_pin_route(world, trip):
    live = world.live_pin(trip["map_id"], by=trip["a"])
    a = world.client(trip["a"])

    for r in (a.get(f"/pins/{live}/reviews"), _put(a, live), a.delete(f"/pins/{live}/reviews/me")):
        assert r.status_code == 422 and r.json()["code"] == "PLACE_NOT_SUPPORTED"


def test_non_member_is_404_like_pin_reactions(world, trip):
    outsider = world.client(world.user("outsider"))
    pin_id = trip["pin_id"]

    same_rule = outsider.get(f"/pins/{pin_id}/reactions")
    responses = [outsider.get(f"/pins/{pin_id}/reviews"), _put(outsider, pin_id),
                 outsider.delete(f"/pins/{pin_id}/reviews/me")]

    assert same_rule.status_code == 404
    assert all(r.status_code == 404 and r.json()["code"] == "NOT_FOUND" for r in responses)
    assert _count(world.db, Review) == 0


def test_unknown_or_deleted_pin_is_404(world, trip):
    world.db.get(Pin, uuid.UUID(trip["pin_id"])).deleted_at = func.now()
    world.db.flush()
    a = world.client(trip["a"])

    assert a.get(f"/pins/{trip['pin_id']}/reviews").status_code == 404
    assert a.get(f"/pins/{uuid.uuid4()}/reviews").status_code == 404
    assert a.get("/pins/not-a-uuid/reviews").status_code == 404


# 20 ---------------------------------------------------------------------------------------------------------------

def test_guest_can_read_but_put_and_report_are_403_without_rows(world, trip):
    guest_id = world.guest()
    world.db.add(Membership(map_id=trip["map_id"], user_id=guest_id, role="member"))
    review_id = world.review(trip["place_id"], trip["a"])
    guest = world.client(guest_id)

    read = guest.get(f"/pins/{trip['pin_id']}/reviews")
    put = _put(guest, trip["pin_id"])
    reported = guest.post(f"/reviews/{review_id}/reports")

    assert read.status_code == 200 and read.json()["summary"]["count"] == 1
    for r in (put, reported):
        assert r.status_code == 403 and r.json()["code"] == "GUEST_NOT_ALLOWED"
        assert r.json()["detail"] == {"initial_credits": INITIAL_CREDITS}
    assert _count(world.db, Review, Review.user_id == guest_id) == 0
    assert _count(world.db, ReviewReport, ReviewReport.reporter_id == guest_id) == 0
    assert _count(world.db, CreditLedger, CreditLedger.user_id == guest_id) == 0
    assert _count(world.db, CreditAccount, CreditAccount.user_id == guest_id) == 0


# 21 ---------------------------------------------------------------------------------------------------------------

def test_hidden_review_leaves_list_average_count_and_mine(world, trip):
    mine = world.review(trip["place_id"], trip["a"], rating=1, body="숨길 글")
    world.review(trip["place_id"], trip["b"], rating=5, body="좋아요")
    set_hidden(world.db, mine, hidden=True)

    body = world.client(trip["a"]).get(f"/pins/{trip['pin_id']}/reviews").json()

    assert body["summary"] == {"average_rating": 5.0, "count": 1}
    assert [i["body"] for i in body["items"]] == ["좋아요"]
    assert "mine" not in body
    assert world.client(trip["b"]).post(f"/reviews/{mine}/reports").status_code == 404   # 숨긴 후기는 신고도 404


def test_editing_a_hidden_review_keeps_it_hidden(world, trip):
    mine = world.review(trip["place_id"], trip["a"])
    set_hidden(world.db, mine, hidden=True)
    a = world.client(trip["a"])

    r = _put(a, trip["pin_id"], body="고친 글")

    assert r.status_code == 200 and r.json()["credited"] == 0
    assert a.get(f"/pins/{trip['pin_id']}/reviews").json()["summary"]["count"] == 0


def test_hidden_review_cannot_be_deleted_so_rewriting_keeps_it_hidden(world, trip):
    """지우고 다시 써서 관리자가 숨긴 글을 되살리지 못한다(#972 검수)."""
    mine = world.review(trip["place_id"], trip["a"], body="숨길 글")
    set_hidden(world.db, mine, hidden=True)
    a = world.client(trip["a"])

    deleted = a.delete(f"/pins/{trip['pin_id']}/reviews/me")
    rewritten = _put(a, trip["pin_id"], body="다시 쓴 글")
    page = a.get(f"/pins/{trip['pin_id']}/reviews").json()

    assert deleted.status_code == 404 and deleted.json()["code"] == "NOT_FOUND"
    assert rewritten.status_code == 200 and rewritten.json()["review"]["id"] == mine
    assert rewritten.json()["credited"] == 0
    assert page["summary"]["count"] == 0 and page["items"] == [] and "mine" not in page
    assert world.db.get(Review, uuid.UUID(mine)).hidden_at is not None


# 22 ---------------------------------------------------------------------------------------------------------------

def test_same_place_on_another_map_shows_the_same_reviews(world, trip):
    c = world.user("c")
    other_map = world.map(c)
    other_pin = world.pin(other_map, trip["place_id"], by=c)
    review_id = _put(world.client(trip["a"]), trip["pin_id"], rating=4, body="성수 최고").json()["review"]["id"]

    seen = world.client(c).get(f"/pins/{other_pin}/reviews").json()

    assert seen["summary"] == {"average_rating": 4.0, "count": 1}
    assert [(i["id"], i["is_mine"]) for i in seen["items"]] == [(review_id, False)]
    assert world.client(c).post(f"/reviews/{review_id}/reports").status_code == 204   # 다른 지도 사람도 볼 수 있어 신고할 수 있다


def test_page_summary_limits_mine_and_cursor(world, trip):
    place_id = trip["place_id"]
    authors = [world.user(f"w{i}") for i in range(PAGE_SIZE + 2)]
    for i, uid in enumerate(authors):
        world.review(place_id, uid, rating=(i % 5) + 1, body=f"후기 {i}")
    world.review(place_id, trip["a"], rating=5, body="내 후기")
    a = world.client(trip["a"])

    first = a.get(f"/pins/{trip['pin_id']}/reviews").json()
    second = a.get(f"/pins/{trip['pin_id']}/reviews", params={"cursor": first["next_cursor"]}).json()

    ratings = [(i % 5) + 1 for i in range(len(authors))] + [5]
    expected_avg = float((Decimal(sum(ratings)) / len(ratings)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    assert first["summary"] == {"average_rating": expected_avg, "count": len(ratings)}
    assert first["limits"] == {"body_max": REVIEW_BODY_MAX}
    assert first["mine"]["body"] == "내 후기" and second["mine"]["body"] == "내 후기"
    assert len(first["items"]) == PAGE_SIZE and "next_cursor" not in second
    ids = [i["id"] for i in first["items"] + second["items"]]
    assert len(ids) == len(set(ids)) == len(ratings)
    assert sum(i["is_mine"] for i in first["items"] + second["items"]) == 1


def test_empty_page_has_null_average_and_no_optional_fields(world, trip):
    body = world.client(trip["a"]).get(f"/pins/{trip['pin_id']}/reviews").json()

    assert body == {"summary": {"average_rating": None, "count": 0}, "limits": {"body_max": REVIEW_BODY_MAX}, "items": []}


def test_bad_cursor_is_422(world, trip):
    r = world.client(trip["a"]).get(f"/pins/{trip['pin_id']}/reviews", params={"cursor": "%%%nope"})

    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"


# 23 ---------------------------------------------------------------------------------------------------------------

def test_report_twice_is_204_twice_with_one_row(world, trip):
    review_id = world.review(trip["place_id"], trip["a"])
    b = world.client(trip["b"])

    assert b.post(f"/reviews/{review_id}/reports").status_code == 204
    assert b.post(f"/reviews/{review_id}/reports").status_code == 204
    assert _count(world.db, ReviewReport, ReviewReport.review_id == uuid.UUID(review_id)) == 1


def test_reporting_my_review_is_422(world, trip):
    review_id = world.review(trip["place_id"], trip["a"])

    r = world.client(trip["a"]).post(f"/reviews/{review_id}/reports")

    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"
    assert _count(world.db, ReviewReport) == 0


def test_reporting_a_review_i_cannot_see_is_404(world, trip):
    review_id = world.review(trip["place_id"], trip["a"])
    outsider = world.user("outsider")
    elsewhere = world.map(outsider)
    world.pin(elsewhere, world.place("다른 가게"), by=outsider)   # 핀은 있지만 다른 장소
    client = world.client(outsider)

    for target in (review_id, str(uuid.uuid4()), "not-a-uuid"):
        r = client.post(f"/reviews/{target}/reports")
        assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"
    assert _count(world.db, ReviewReport) == 0


# 24 ---------------------------------------------------------------------------------------------------------------

def test_no_response_carries_author_name_or_user_id(world, trip):
    a = world.client(trip["a"])
    saved = _put(a, trip["pin_id"]).json()
    world.review(trip["place_id"], trip["b"])
    page = a.get(f"/pins/{trip['pin_id']}/reviews").json()

    text = str(saved) + str(page)
    for user_id in (trip["a"], trip["b"]):
        assert user_id not in text
    assert set(page["items"][0]) == {"id", "rating", "body", "created_at", "updated_at", "is_mine"}
    assert set(saved["review"]) == set(page["mine"]) == {"id", "rating", "body", "created_at", "updated_at"}

