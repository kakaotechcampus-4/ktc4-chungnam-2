"""recommend.api.get_readiness(#530) — agent의 반대 후 정체 진단(docs/agent-v2.md 6.2)이 본다.
라우터 `GET /maps/{mapId}/recommend/readiness`와 같은 값이어야 한다(계산은 flows.readiness_for_category 한 곳)."""

import pytest

from common import categories
from recommend import api
from recommend.tests.test_router import _auth, _seed_ready_map, app_client  # noqa: F401 — 픽스처 재사용


def test_matches_router_response_for_every_recommendable_category(app_client, db_session):  # noqa: F811
    _seed_ready_map(db_session)  # 음식점 핀 하나에 user_1의 ♥

    body = app_client.get("/maps/map_1/recommend/readiness", cookies=_auth()).json()

    for category in categories.recommendable():
        assert api.get_readiness(db_session, map_id="map_1", category=category) == body[category]


def test_returns_count_shape(app_client, db_session):  # noqa: F811
    _seed_ready_map(db_session)

    assert api.get_readiness(db_session, map_id="map_1", category="음식점") == {
        "ready": True, "answered_count": 1, "required_count": 1,
    }
    assert api.get_readiness(db_session, map_id="map_1", category="카페") == {
        "ready": False, "answered_count": 0, "required_count": 1,
    }


@pytest.mark.parametrize("category", ["숙소", "기타", "없는카테고리"])
def test_non_recommendable_category_raises(db_session, category):
    """라우터 응답에도 이 키가 없다 — 지어낸 판정을 돌려주지 않는다."""
    with pytest.raises(ValueError):
        api.get_readiness(db_session, map_id="map_1", category=category)
