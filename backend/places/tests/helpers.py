"""테스트 공용 — 네트워크 없이 httpx.MockTransport로 소스 응답을 흉내낸다."""

from __future__ import annotations

import httpx

from places.http import CallStats, SourceHttp


def make_http(handler, *, retries: int = 0) -> tuple[SourceHttp, CallStats, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    stats = CallStats()
    client = httpx.Client(transport=httpx.MockTransport(wrapped), timeout=3.0)
    return SourceHttp(client, stats, retries=retries), stats, seen


def json_response(body: dict, status: int = 200):
    return lambda request: httpx.Response(status, json=body)


KAKAO_DOC = {
    "id": "111", "place_name": "성수 칼국수", "category_group_code": "FD6", "phone": "02-111-2222",
    "address_name": "서울 성동구 성수동", "road_address_name": "서울 성동구 아차산로 1",
    "x": "127.0561", "y": "37.5445", "place_url": "http://place.map.kakao.com/111",
}
