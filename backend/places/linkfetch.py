"""단축 링크(maps.app.goo.gl·goo.gl·kko.to)를 따라가 최종 주소를 얻는다(#474). SSRF 방어가 이 파일의 일이다.

- http(s)만, 포트는 기본(80/443)만, 호스트는 linkparse의 도메인 허용목록만 — 리다이렉트가 허용목록 밖으로 가면 멈춘다.
- 리다이렉트는 직접 따라가며(최대 MAX_REDIRECTS) 매 홉마다 호스트를 다시 검사하고 DNS를 풀어 **전부 공인 IP인지** 본다
  (사설·루프백·링크로컬·예약 대역 차단). 검사한 IP로 직접 접속한다 — 검사와 접속 사이에 DNS가 바뀌는 것(rebinding)을 막는다.
- 본문은 읽지 않는다(스트림으로 받아 헤더만 보고 닫는다) — 크기 제한을 따로 둘 필요가 없다. 타임아웃은 호출당 짧게.
- 단축 호스트가 아닌 주소(이미 긴 지도 주소)는 가져오지 않고 그대로 돌려준다.
로그에는 링크 주소를 남기지 않는다(이름·좌표가 들어 있을 수 있다).
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Callable
from urllib.parse import urljoin, urlsplit

import httpx

from places import linkparse

MAX_REDIRECTS = 4
TIMEOUT_S = 3.0
MAX_LOCATION_LEN = linkparse.MAX_URL_LEN
_REDIRECT_STATUS = {301, 302, 303, 307, 308}


class LinkFetchError(Exception):
    """단축 링크를 열지 못했다(허용 밖 이동·사설 IP·횟수 초과·네트워크 실패). 호출한 쪽이 LINK_UNRESOLVED로 바꾼다."""


def make_client() -> httpx.Client:
    # 리다이렉트는 직접 따라간다. 환경의 프록시 설정을 타지 않는다(trust_env=False) — 프록시가 사설 대역 검사를 우회할 수 있다.
    return httpx.Client(timeout=TIMEOUT_S, follow_redirects=False, trust_env=False)


def resolve_public_ip(host: str, port: int) -> str:
    """호스트를 풀어 나온 주소가 전부 공인 IP일 때만 그중 하나를 돌려준다. 하나라도 아니면 LinkFetchError."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise LinkFetchError("DNS 조회 실패") from exc
    ips = [info[4][0] for info in infos]
    if not ips or not all(is_public_ip(ip) for ip in ips):
        raise LinkFetchError("공인 IP가 아닌 주소")
    return ips[0]


def is_public_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped   # ::ffff:10.0.0.1 로 사설 대역을 숨기는 경우
    return addr.is_global and not addr.is_multicast


def follow_short_link(
    url: str,
    *,
    client: httpx.Client,
    resolve: Callable[[str, int], str] = resolve_public_ip,
) -> str:
    """단축 링크를 따라가 처음 나오는 '단축이 아닌' 허용 주소를 돌려준다."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        parts = urlsplit(current)
        host = (parts.hostname or "").lower().rstrip(".")
        if parts.scheme not in ("http", "https") or parts.username or parts.password or not linkparse.is_allowed_host(host):
            raise LinkFetchError("허용되지 않은 주소")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        if port not in (80, 443):
            raise LinkFetchError("허용되지 않은 포트")
        if not linkparse.is_short_host(host):
            return current
        ip = resolve(host, port)
        literal = f"[{ip}]" if ":" in ip else ip
        pinned = parts._replace(netloc=literal if parts.port is None else f"{literal}:{parts.port}").geturl()
        try:
            with client.stream(
                "GET", pinned, headers={"Host": host, "Accept": "*/*"},
                extensions={"sni_hostname": host}, follow_redirects=False,
            ) as resp:
                location = resp.headers.get("location") if resp.status_code in _REDIRECT_STATUS else None
        except httpx.HTTPError as exc:
            raise LinkFetchError(type(exc).__name__) from exc
        if not location or len(location) > MAX_LOCATION_LEN:
            raise LinkFetchError("리다이렉트가 아니다")
        current = urljoin(current, location)
    raise LinkFetchError("리다이렉트가 너무 많다")
