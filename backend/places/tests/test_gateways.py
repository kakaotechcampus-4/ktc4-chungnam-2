"""pins/recommend real 슬롯 — 계약 일치, 타입 변환, PLACES_MODE=real 기동."""

import os
import subprocess
import sys
from pathlib import Path

from common.contracts import assert_signature_matches
from pins.deps import RealPlaceGateway
from pins.ports import PinDraft, PlaceGateway, ResolvedPlace
from places import api
from places.schemas import PlaceRef
from recommend.deps import RealPlaceFactsGateway, RealPlaceSearchGateway
from recommend.ports import Circle, PlaceFactsGateway, PlaceSearchGateway, PlaceStub

BACKEND = Path(__file__).resolve().parents[2]


def test_real_gateways_match_their_protocols():
    assert_signature_matches(PlaceGateway, RealPlaceGateway)
    assert_signature_matches(PlaceSearchGateway, RealPlaceSearchGateway)
    assert_signature_matches(PlaceFactsGateway, RealPlaceFactsGateway)


def test_pins_gateway_returns_pins_type(monkeypatch):
    resolved = api.ResolvedCoords("kakao:1", 37.1, 127.1)
    monkeypatch.setattr(api, "resolve_place", lambda *a: resolved)
    out = RealPlaceGateway().resolve(PinDraft(source="search", place_id="kakao:1", lat=None, lng=None))
    assert out == ResolvedPlace(place_id="kakao:1", lat=37.1, lng=127.1)


def test_recommend_gateway_converts_circles_and_results(monkeypatch):
    got = {}

    def fake_search(category, areas):
        got["args"] = (category, list(areas))
        return [PlaceRef("kakao:1", 37.5, 127.0)]

    monkeypatch.setattr(api, "search_nearby", fake_search)
    stubs = RealPlaceSearchGateway().search_nearby(category="카페", circles=[Circle(37.5, 127.0, 800)])
    assert stubs == [PlaceStub(place_id="kakao:1", lat=37.5, lng=127.0)]
    assert got["args"][0] == "카페" and got["args"][1][0].radius_m == 800


def test_facts_gateway_delegates(monkeypatch):
    monkeypatch.setattr(api, "get_raw_facts", lambda pid: {"name": pid})
    assert RealPlaceFactsGateway().get_raw_facts("kakao:1") == {"name": "kakao:1"}


def test_server_boots_with_places_mode_real_and_fills_all_three_slots():
    env = {**os.environ, "PLACES_MODE": "real", "PINGO_ENV": "dev"}
    code = "import main; from common.adapters import assembly; print([(c.port, c.mode) for c in assembly()])"
    out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    for port in ("pins.PlaceGateway", "recommend.PlaceSearchGateway", "recommend.PlaceFactsGateway"):
        assert f"('{port}', 'real')" in out.stdout
