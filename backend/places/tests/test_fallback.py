"""폴백 우선순위(카카오→네이버→그다음 소스)와 "상위가 채운 필드는 하위가 다시 조회하지 않는다"."""

from places.http import SourceError
from places.sources.base import ENRICHABLE_FIELDS, RawPlace
from places import fallback


class FakeSource:
    def __init__(self, name, *, provides=(), configured=True, nearby=None, fills=None, fail=False):
        self.name = name
        self.provides = frozenset(provides)
        self._configured = configured
        self._nearby = nearby or []
        self._fills = fills or {}
        self._fail = fail
        self.nearby_calls = 0
        self.fill_asks: list[frozenset[str]] = []

    def is_configured(self):
        return self._configured

    def search_nearby(self, **_):
        self.nearby_calls += 1
        if self._fail:
            raise SourceError(f"{self.name} down")
        return self._nearby

    def fill(self, place, wanted):
        self.fill_asks.append(wanted)
        if self._fail:
            raise SourceError(f"{self.name} down")
        return self._fills


def place(source="kakao", **kw):
    base = dict(source=source, source_id="1", name="가게", lat=37.5, lng=127.0, category="음식점",
                contributed_by=(source,))
    base.update(kw)
    return RawPlace(**base)


# ---- 보완(enrich) ----

def test_already_filled_fields_are_not_asked_again():
    p = place(phone="02-1")   # 카카오가 전화를 이미 채웠다
    n = FakeSource("naver", provides={"phone"}, fills={"phone": "다른 번호"})
    g = FakeSource("other", provides=ENRICHABLE_FIELDS,
                   fills={"rating": 4.0, "rating_count": 10, "opening_hours": ("월 9-18",)})
    out = fallback.enrich(p, [FakeSource("kakao", provides={"phone"}), n, g])
    assert n.fill_asks == []                                    # 네이버는 남은 필드를 못 주니 호출 자체가 없다
    assert g.fill_asks == [frozenset({"rating", "opening_hours"})]   # phone은 묻지 않는다
    assert out.phone == "02-1" and out.rating == 4.0 and out.contributed_by == ("kakao", "other")


def test_enrich_stops_once_everything_is_filled():
    p = place(phone="1", rating=4.0, opening_hours=("x",))
    g = FakeSource("other", provides=ENRICHABLE_FIELDS)
    assert fallback.enrich(p, [g]) is p and g.fill_asks == []


def test_enrich_never_overwrites_existing_value():
    p = place(phone="02-1")
    n = FakeSource("naver", provides={"phone"}, fills={"phone": "덮어쓰기 시도"})
    # phone이 wanted에 안 들어가므로 애초에 묻지 않는다 — 그래도 merged 자체가 방어한다
    assert p.merged({"phone": "덮어쓰기 시도"}, "naver", frozenset({"phone"})).phone == "02-1"
    assert fallback.enrich(p, [n]).phone == "02-1"


def test_enrich_survives_a_failing_source_and_tries_the_next():
    g = FakeSource("other", provides=ENRICHABLE_FIELDS, fills={"rating": 3.5, "rating_count": 3})
    out = fallback.enrich(place(phone="1"), [FakeSource("naver", provides={"phone"}, fail=True), g])
    assert out.rating == 3.5


def test_enrich_skips_sources_without_key():
    g = FakeSource("other", provides=ENRICHABLE_FIELDS, configured=False)
    fallback.enrich(place(), [g])
    assert g.fill_asks == []
