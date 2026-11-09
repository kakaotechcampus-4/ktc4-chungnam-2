"""장소 블로그 사진(#1157) — 카카오(다음) 이미지 검색으로 그 가게를 다룬 블로그 사진의 미리보기를 찾는다.

카카오 로컬 API와 같은 규칙(#53)을 지킨다: 응답은 화면에 넘기고 버린다. 저장, 캐시, 모델 입력을 하지 않고,
로그에는 호출 횟수만 남긴다(`SourceHttp`). 사진 원본이 아니라 카카오가 만든 미리보기(`thumbnail_url`)를 쓰고,
출처 사이트 이름과 원문 주소를 같이 넘겨 화면이 출처를 밝히고 원문으로 보낸다.

검색어는 상호명과 구, 도로명 주소다. 2026-11-10 표본 10곳(프랜차이즈 6곳, 개인 가게 4곳)을 비교했다:
상호명만 찾으면 프랜차이즈는 지점과 상관없이 본사 홍보 사진이 나오고, 동 이름 + 상호명은 다른 브랜드가 섞였다.
주소를 붙이면 그 주소를 적은 블로그 글, 곧 그 지점에 다녀온 글의 사진이 나왔다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from places.http import SourceHttp

IMAGE_URL = "https://dapi.kakao.com/v2/search/image"

# 블로그 사진 중 그 가게 사진이 아닌 것이 오는 곳(같은 표본으로 확인): 네이버 블로그 이모티콘, 글에 붙인 지도 캡처, 링크 미리보기.
SKIP_HOSTS = frozenset({"storep-phinf.pstatic.net", "simg.pstatic.net", "dthumb-phinf.pstatic.net"})
# 짧은 변이 이보다 작으면 아이콘이나 미리보기 조각이다.
MIN_SIDE = 300
# 화면에 보이는 장수. 걸러 낼 몫을 두고 이만큼 받는다.
PHOTO_LIMIT = 3
FETCH_SIZE = 15

_PAREN = re.compile(r"\(.*?\)")


@dataclass(frozen=True)
class PlacePhoto:
    """블로그 사진 한 장 — 카카오 미리보기 주소, 원문 글 주소, 출처 사이트 이름."""

    thumbnail_url: str
    link_url: str
    site_name: str


def photo_query(name: str | None, address: str | None) -> str | None:
    """검색어 = 상호명과 구, 도로명 주소. 상호명의 괄호(지점명), 주소의 괄호(법정동)와 쉼표 뒤(건물, 층)는 떼고, 맨 앞 시나 도는 뺀다.
    이름이나 주소가 없으면 검색하지 않는다 — 상호명만으로는 다른 지점 사진이 섞인다."""
    base = _PAREN.sub("", name or "").strip()
    # 주소의 괄호는 법정동 같은 덧붙임이고 겹친 경우도 있어("구로중앙로 5 (구로동,(구로큰길 178))") 첫 괄호부터 뒤를 뗀다.
    street = (address or "").split("(")[0].split(",")[0].strip()
    if not base or not street:
        return None
    parts = street.split()
    if parts and parts[0].endswith(("시", "도")):
        parts = parts[1:]
    return f"{base} {' '.join(parts)}".strip() if parts else None


def pick(documents: list[dict[str, Any]], limit: int = PHOTO_LIMIT) -> list[PlacePhoto]:
    """검색 결과에서 그 가게 사진일 만한 것만 위에서부터 limit장 고른다. 필드가 빠진 결과는 건너뛴다."""
    out: list[PlacePhoto] = []
    for d in documents:
        thumb, link, image = d.get("thumbnail_url"), d.get("doc_url"), d.get("image_url")
        width, height = d.get("width") or 0, d.get("height") or 0
        if not (thumb and link and image):
            continue
        if urlparse(image).netloc in SKIP_HOSTS or min(width, height) < MIN_SIDE:
            continue
        out.append(PlacePhoto(thumbnail_url=thumb, link_url=link, site_name=d.get("display_sitename") or ""))
        if len(out) >= limit:
            break
    return out


class KakaoImageSearch:
    """다음 이미지 검색 API 호출만 한다. 결과는 돌려주고 들고 있지 않는다."""

    name = "kakao_image"

    def __init__(self, http: SourceHttp, api_key: str) -> None:
        self._http = http
        self._key = api_key

    def is_configured(self) -> bool:
        return bool(self._key)

    def search(self, query: str) -> list[dict[str, Any]]:
        body = self._http.request_json(
            self.name, "image", "GET", IMAGE_URL,
            headers={"Authorization": f"KakaoAK {self._key}"},
            params={"query": query, "size": FETCH_SIZE, "sort": "accuracy"},
        )
        return list(body.get("documents", []))
