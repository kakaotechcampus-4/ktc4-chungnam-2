"""지도 링크 해석(#474)의 순수 부분 — 링크 문자열에서 구글맵 이름·좌표나 카카오 장소 ID를 읽는다. 네트워크·DB를 모른다.

구글 링크에서 읽은 좌표와 이름은 자체 DB를 찾는 데만 쓰고 응답·로그에 싣지 않는다(저장·로깅 금지, #53).
카카오 링크에서는 장소 ID(저장이 허용된 유일한 값)만 읽는다 — 이름·좌표가 들어 있어도 쓰지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote_plus, urlsplit

from common.errors import AppError

MAX_URL_LEN = 2000
MAX_NAME_LEN = 100   # LinkParseResult.name_hint 상한

# 도메인 허용목록 — 정확히 같거나 그 하위 도메인. 네이버(naver.me·map.naver.com)는 일부러 없다(#134).
_ALLOWED_DOMAINS = ("google.com", "google.co.kr", "goo.gl", "kakao.com", "kko.to")
# 이 호스트는 리다이렉트를 따라가야 최종 주소를 안다. 그 밖의 허용 호스트는 받은 주소를 바로 읽는다.
_SHORT_HOSTS = ("maps.app.goo.gl", "goo.gl", "kko.to")

_COORD_PLACE = re.compile(r"!3d(-?\d{1,3}\.\d+)!4d(-?\d{1,3}\.\d+)")   # 장소 핀의 좌표(뷰포트 중심보다 정확하다)
_COORD_VIEW = re.compile(r"@(-?\d{1,3}\.\d+),(-?\d{1,3}\.\d+)")
_COORDS_ONLY = re.compile(r"-?\d{1,3}(\.\d+)?\s*,\s*-?\d{1,3}(\.\d+)?")
_KAKAO_ID_PATH = re.compile(r"/(?:m/)?(\d{1,20})/?")
_KAKAO_ID = re.compile(r"\d{1,20}")


@dataclass(frozen=True)
class ParsedLink:
    provider: str                       # "google" | "kakao"
    name_hint: str | None = None        # 구글만
    lat: float | None = None            # 구글만, 내부용 — 응답·로그에 싣지 않는다
    lng: float | None = None
    kakao_place_id: str | None = None   # 카카오만 "kakao:<id>"


def split_url(raw: str):
    """http(s) 링크만 받는다. 허용 호스트가 아니거나 형태가 이상하면 LINK_NOT_SUPPORTED."""
    url = raw.strip()
    if not url or len(url) > MAX_URL_LEN:
        raise AppError("LINK_NOT_SUPPORTED")
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        raise AppError("LINK_NOT_SUPPORTED") from None
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme not in ("http", "https") or not host or parts.username or parts.password or port not in (None, 80, 443):
        raise AppError("LINK_NOT_SUPPORTED")
    if not is_allowed_host(host):
        raise AppError("LINK_NOT_SUPPORTED")
    return parts


def is_allowed_host(host: str) -> bool:
    return any(host == d or host.endswith("." + d) for d in _ALLOWED_DOMAINS)


def is_short_host(host: str) -> bool:
    return host in _SHORT_HOSTS


def parse_resolved(url: str) -> ParsedLink | None:
    """단축을 풀고 난 주소(또는 처음부터 긴 주소)에서 단서를 읽는다.
    구글·카카오 지도 주소가 아니면 None(형식을 모른다). 지도 주소인데 장소를 가리키지 않으면(보고 있는 화면뿐·좌표만 등) LINK_UNRESOLVED."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    if _under(host, "kakao.com"):
        return _parse_kakao(parts)
    if _under(host, "google.com") or _under(host, "google.co.kr"):
        return _parse_google(parts)
    return None


def _under(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def _parse_kakao(parts) -> ParsedLink | None:
    host = (parts.hostname or "").lower()
    raw = None
    if host.startswith("place.map.") or host.startswith("m.place.map."):
        m = _KAKAO_ID_PATH.fullmatch(parts.path)
        raw = m.group(1) if m else None
    else:
        q = parse_qs(parts.query)
        for key in ("itemId", "id"):
            value = (q.get(key) or [""])[0]
            if _KAKAO_ID.fullmatch(value):
                raw = value
                break
    if raw is None:
        if host.startswith(("place.map.", "m.place.map.", "map.", "m.map.")):
            raise AppError("LINK_UNRESOLVED")   # 카카오맵 주소지만 장소 ID가 없다(좌표·검색 링크 등)
        return None
    return ParsedLink("kakao", kakao_place_id=f"kakao:{raw}")


def _parse_google(parts) -> ParsedLink | None:
    if not (parts.path.startswith("/maps") or (parts.hostname or "").lower().startswith("maps.")):
        return None   # google.com/search 같은 지도 아닌 주소
    name = _google_name(parts)
    if name is None:
        raise AppError("LINK_UNRESOLVED")   # 구글 지도 주소지만 장소 이름이 없다(보고 있는 화면·좌표뿐)
    # 경로 전체(`!3d..!4d..`는 data 세그먼트에 있다)에서 좌표를 읽는다
    coord = _COORD_PLACE.search(parts.path) or _COORD_VIEW.search(parts.path)
    lat, lng = (float(coord.group(1)), float(coord.group(2))) if coord else (None, None)
    if lat is not None and not (-90 <= lat <= 90 and -180 <= lng <= 180):
        lat = lng = None
    return ParsedLink("google", name_hint=name, lat=lat, lng=lng)


def _google_name(parts) -> str | None:
    segments = [s for s in parts.path.split("/") if s]
    name = None
    if "place" in segments[:-1]:
        name = segments[segments.index("place") + 1]
    else:
        q = parse_qs(parts.query)
        for key in ("q", "query"):
            if q.get(key):
                name = q[key][0]
                break
    if not name:
        return None
    name = unquote_plus(name).strip()
    if not name or _COORDS_ONLY.fullmatch(name):
        return None   # 좌표만 있는 주소는 장소 이름이 아니다
    return name[:MAX_NAME_LEN]
