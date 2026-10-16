"""순수 함수 테스트 — DB 없이 돌아간다(docs/code-quality.md)."""

from dataclasses import dataclass

from authz.core import Principal
from authz.schemas import Permissions
from shortlist import core
from shortlist.schemas import Route, RouteLeg, ShortlistItem


@dataclass
class _FakeRow:
    id: str
    map_id: str
    added_by: str
    visit_order: int | None = None


def _pin(map_id="map_1", pin_id="pin_1"):
    return {
        "id": pin_id, "map_id": map_id, "category": "음식점", "kind": "확정",
        "visibility": "public", "lat": 35.1, "lng": 129.0, "created_by": "user_1",
        "reaction_summary": {"like": 0, "against": 0},
        "permissions": {},
    }


def _principal(role="member"):
    return Principal(user_id="user_1", map_id="map_1", role=role)


def test_to_shortlist_item_response_carries_row_fields_and_pin():
    from pins.schemas import Pin

    row = _FakeRow(id="item_1", map_id="map_1", added_by="user_1", visit_order=3)
    pin = Pin(**_pin())

    item = core.to_shortlist_item_response(row, pin, _principal())

    assert item.id == "item_1"
    assert item.pin is pin
    assert item.visit_order == 3
    assert item.added_by == "user_1"


def test_to_shortlist_item_response_permissions_reflect_member_role():
    from pins.schemas import Pin

    row = _FakeRow(id="item_1", map_id="map_1", added_by="user_1")
    pin = Pin(**_pin())

    item = core.to_shortlist_item_response(row, pin, _principal(role="member"))
    assert item.permissions.can_remove_from_shortlist is True
    assert item.permissions.can_add_to_shortlist is False  # 이미 리스트에 있는 항목이라 항상 False

    item_non_member = core.to_shortlist_item_response(row, pin, _principal(role=None))
    # can()은 role=None이면 항상 False(authz/core.py) — 비구성원 표시는 실제로는 404로 먼저
    # 끝나 이 값을 FE가 보진 않지만, 함수 자체의 순수성은 이렇게 확인한다.
    assert item_non_member.permissions.can_remove_from_shortlist is False


def test_shortlist_changed_event_uses_pin_map_id_and_public_channel():
    item = ShortlistItem(
        id="item_1", pin=_pin(map_id="map_9"), visit_order=None, added_by="user_1",
        permissions=Permissions(),
    )
    event = core.shortlist_changed_event(item, "added")

    assert event.map_id == "map_9"
    assert event.channel == "public"
    assert event.type == "shortlist.changed"
    assert event.payload["action"] == "added"
    assert event.payload["item"]["id"] == "item_1"


@dataclass
class _FakeRouteRow:
    region_label: str
    ordered_pin_ids: list
    total_distance_m: float
    legs: list


def test_to_route_response_rebuilds_legs_from_jsonb():
    row = _FakeRouteRow(
        region_label="구역 1", ordered_pin_ids=["pin_1", "pin_2"], total_distance_m=150.0,
        legs=[{"from_pin_id": "pin_1", "to_pin_id": "pin_2", "distance_m": 150.0, "approx_minutes": 2}],
    )

    route = core.to_route_response(row)

    assert route.region_label == "구역 1"
    assert route.ordered_pin_ids == ["pin_1", "pin_2"]
    assert route.total_distance_m == 150.0
    assert route.legs == [RouteLeg(from_pin_id="pin_1", to_pin_id="pin_2", distance_m=150.0, approx_minutes=2)]


def test_route_recalculated_event_payload_is_a_bare_list_not_wrapped():
    """docs/events.md route.recalculated — data는 다른 이벤트처럼 객체로 감싸지 않고 Route[] 그대로다."""
    routes = [Route(region_label="구역 1", ordered_pin_ids=["pin_1"], total_distance_m=0, legs=[])]
    event = core.route_recalculated_event("map_9", routes)

    assert event.map_id == "map_9"
    assert event.channel == "public"
    assert event.type == "route.recalculated"
    assert isinstance(event.payload, list)
    assert event.payload == [{"region_label": "구역 1", "ordered_pin_ids": ["pin_1"], "total_distance_m": 0, "legs": []}]


def test_reorder_mismatch_none_for_same_set_any_order():
    assert core.reorder_mismatch(["a", "b", "c"], ["c", "a", "b"]) is None
    assert core.reorder_mismatch([], []) is None


def test_reorder_mismatch_reports_missing_unknown_duplicated():
    assert core.reorder_mismatch(["a", "b"], ["a"]) == {"duplicated": [], "missing": ["b"], "unknown": []}
    assert core.reorder_mismatch(["a"], ["a", "x"])["unknown"] == ["x"]
    assert core.reorder_mismatch(["a", "b"], ["a", "a", "b"])["duplicated"] == ["a"]


# --- 확정 리스트 내보내기(#471) ---

def _export_pin(**overrides):
    from pins.schemas import Pin

    return Pin(**{**_pin(), **overrides})


def _live_pin(**overrides):
    live = {"source": "live", "lat": None, "lng": None, "kakao_place_id": "kakao:555", "search_query": "성수 곱창", "memo": "맛있대",
            "place_url": "https://place.map.kakao.com/555"}
    return _export_pin(**{**live, **overrides})


def test_to_export_row_db_pin_uses_place_name_and_url_without_coordinates():
    row = core.to_export_row(1, _export_pin(place_name="성수 칼국수", place_url="https://place.map.kakao.com/1", memo="웨이팅"))

    assert row == core.ExportRow(1, "성수 칼국수", "음식점", "https://place.map.kakao.com/1", "웨이팅")


def test_to_export_row_live_pin_uses_search_query_with_name_check_suffix_and_kakao_link():
    row = core.to_export_row(2, _live_pin())

    assert row.name == "성수 곱창 (이름 확인 필요)"
    assert row.link == "https://place.map.kakao.com/555"
    assert row.memo == "맛있대"


def test_to_export_row_live_pin_link_is_pin_place_url_as_is():
    assert core.to_export_row(1, _live_pin(place_url="https://place.map.kakao.com/777")).link == "https://place.map.kakao.com/777"


def test_to_export_row_live_pin_without_place_url_leaves_link_empty():
    assert core.to_export_row(1, _live_pin(place_url=None)).link == ""


def test_to_export_row_does_not_expose_reactions_or_coordinates():
    row = core.to_export_row(1, _live_pin(my_reaction={"pin_id": "pin_1", "user_id": "user_1", "type": "against", "reason_text": "비밀 사유"}))

    assert "비밀" not in repr(row)
    assert set(vars(row)) == {"order", "name", "category", "link", "memo"}


def test_render_csv_starts_with_bom_uses_crlf_and_escapes_cells():
    rows = [core.ExportRow(1, 'A, "B"', "음식점", "https://x", "줄1\n줄2")]

    out = core.render_csv(rows)

    assert out == '\ufeff순서,이름,분류,링크,메모\r\n1,"A, ""B""",음식점,https://x,"줄1\n줄2"\r\n'


def test_render_csv_prefixes_formula_cells_with_apostrophe():
    rows = [core.ExportRow(1, "=SUM(A1)", "음식점", "", "-1 @a +b")]

    assert core.render_csv(rows).splitlines()[1] == "1,'=SUM(A1),음식점,,'-1 @a +b"


def test_render_csv_empty_list_is_header_only():
    assert core.render_csv([]) == "\ufeff순서,이름,분류,링크,메모\r\n"


def test_render_txt_one_line_per_place_with_link_and_memo():
    rows = [
        core.ExportRow(1, "성수 칼국수", "음식점", "https://p/1", "웨이팅\n길다"),
        core.ExportRow(2, "성수 곱창 (이름 확인 필요)", "음식점", "", ""),
    ]

    assert core.render_txt(rows) == (
        "1. 성수 칼국수 (음식점) https://p/1 — 웨이팅 길다\n"
        "2. 성수 곱창 (이름 확인 필요) (음식점)\n"
    )


def test_render_txt_empty_list_is_one_notice_line():
    assert core.render_txt([]) == "확정한 장소가 아직 없어요\n"


def test_export_basename_uses_title_and_default_when_missing_or_blank():
    assert core.export_basename("부산 여행") == "부산 여행 확정 리스트"
    assert core.export_basename(None) == "확정 리스트"
    assert core.export_basename("   ") == "확정 리스트"
    assert core.export_basename(" . ") == "확정 리스트"


def test_export_basename_strips_path_chars_control_chars_and_edge_dots():
    assert core.export_basename('a/b\\c:d*e?f"g<h>i|j') == "abcdefghij 확정 리스트"
    assert core.export_basename("부산\r\n여행\x00‮") == "부산 여행 확정 리스트"
    assert core.export_basename("..제목..") == "제목 확정 리스트"
    assert core.export_basename('/\\:*?"<>|') == "확정 리스트"


def test_export_basename_limits_title_length():
    assert core.export_basename("가" * 200) == "가" * 50 + " 확정 리스트"


def test_export_content_disposition_has_rfc5987_name_and_ascii_fallback():
    out = core.export_content_disposition("부산 여행", "csv")

    assert out == (
        'attachment; filename="shortlist.csv"; '
        "filename*=UTF-8''%EB%B6%80%EC%82%B0%20%EC%97%AC%ED%96%89%20%ED%99%95%EC%A0%95%20%EB%A6%AC%EC%8A%A4%ED%8A%B8.csv"
    )


def test_export_content_disposition_ascii_title_goes_into_fallback_too():
    assert core.export_content_disposition("Busan", "txt").startswith('attachment; filename="Busan 확정 리스트.txt"'.replace(" 확정 리스트", ""))


def test_export_content_disposition_cannot_inject_header_lines():
    out = core.export_content_disposition('x"\r\nSet-Cookie: a=b; y', "csv")

    assert "\r" not in out and "\n" not in out
    assert out.count('"') == 2
    assert out.endswith(".csv")
