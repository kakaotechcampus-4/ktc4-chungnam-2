"""호출 안전 — 재시도 한도, 타임아웃 처리, 호출 횟수 집계."""

import httpx
import pytest

from places.http import CallStats, SourceError, SourceHttp
from places.tests.helpers import make_http


def _get(http: SourceHttp):
    return http.request_json("kakao", "category", "GET", "https://example.test/x", headers={})


def test_retries_once_on_503_then_succeeds():
    replies = iter([httpx.Response(503), httpx.Response(200, json={"ok": True})])
    http, stats, seen = make_http(lambda r: next(replies), retries=1)
    assert _get(http) == {"ok": True}
    assert len(seen) == 2 and stats.count("kakao") == 2   # 재시도도 호출 횟수에 센다


def test_gives_up_after_retry_limit():
    http, stats, seen = make_http(lambda r: httpx.Response(500), retries=1)
    with pytest.raises(SourceError, match="500"):
        _get(http)
    assert len(seen) == 2


def test_does_not_retry_client_errors():
    http, _, seen = make_http(lambda r: httpx.Response(401), retries=3)
    with pytest.raises(SourceError, match="401"):
        _get(http)
    assert len(seen) == 1


def test_timeout_is_a_source_error_after_retries():
    def boom(request):
        raise httpx.ReadTimeout("slow", request=request)

    http, _, seen = make_http(boom, retries=1)
    with pytest.raises(SourceError, match="ReadTimeout"):
        _get(http)
    assert len(seen) == 2


def test_non_json_body_is_a_source_error():
    http, _, _ = make_http(lambda r: httpx.Response(200, text="<html>"))
    with pytest.raises(SourceError, match="JSON"):
        _get(http)


def test_stats_snapshot_counts_per_source():
    stats = CallStats()
    stats.incr("kakao"); stats.incr("kakao"); stats.incr("naver")
    assert stats.snapshot() == {"kakao": 2, "naver": 1}
