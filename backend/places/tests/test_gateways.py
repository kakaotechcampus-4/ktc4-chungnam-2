"""recommend real 슬롯(pins는 #195부터 places.api를 직접 부른다 — 어댑터 슬롯 없음) — 계약 일치, 타입 변환, PLACES_MODE=real 기동."""

import os
import subprocess
import sys
from pathlib import Path

from common.contracts import assert_signature_matches
from places import api
from places.schemas import PlaceRef
from recommend.deps import RealPlaceFactsGateway, RealPlaceSearchGateway
from recommend.ports import Circle, PlaceFactsGateway, PlaceSearchGateway, PlaceStub

BACKEND = Path(__file__).resolve().parents[2]


def test_real_gateways_match_their_protocols():
    assert_signature_matches(PlaceSearchGateway, RealPlaceSearchGateway)
    assert_signature_matches(PlaceFactsGateway, RealPlaceFactsGateway)


def test_recommend_gateway_converts_circles_and_results(monkeypatch):
    """#190 — 후보 풀은 자체 DB(search_nearby_own)에서 온다. 카카오 실시간 search_nearby는 부르지 않는다."""
    got = {}

    def fake_search(category, areas, *, db=None):
        got["args"] = (category, list(areas))
        return [PlaceRef("5b0e2f3a-0000-0000-0000-000000000001", 37.5, 127.0)]

    monkeypatch.setattr(api, "search_nearby_own", fake_search)
    monkeypatch.setattr(api, "search_nearby", lambda *a, **k: (_ for _ in ()).throw(AssertionError("카카오 실시간 경로")))
    stubs = RealPlaceSearchGateway().search_nearby(category="카페", circles=[Circle(37.5, 127.0, 800)])
    assert stubs == [PlaceStub(place_id="5b0e2f3a-0000-0000-0000-000000000001", lat=37.5, lng=127.0)]
    assert got["args"][0] == "카페" and got["args"][1][0].radius_m == 800


def test_facts_gateway_delegates(monkeypatch):
    from places.schemas import FactLabel

    labels = {"p1": [FactLabel("quiet", True, "known")]}
    monkeypatch.setattr(api, "get_facts", lambda ids, *, db=None: labels)
    assert RealPlaceFactsGateway().get_facts(["p1"]) == labels


def test_server_boots_with_places_mode_real_and_fills_recommend_slots():
    env = {**os.environ, "PLACES_MODE": "real", "PINGO_ENV": "dev"}
    code = "import main; from common.adapters import assembly; print([(c.port, c.mode) for c in assembly()])"
    out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    for port in ("recommend.PlaceSearchGateway", "recommend.PlaceFactsGateway"):
        assert f"('{port}', 'real')" in out.stdout
