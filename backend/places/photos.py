"""장소 블로그 사진(#1157) — 카카오(다음) 이미지 검색으로 그 가게를 다룬 블로그 사진의 미리보기를 찾는다.

카카오 로컬 API와 같은 규칙(#53)을 지킨다: 응답은 화면에 넘기고 버린다. 저장, 캐시, 모델 입력을 하지 않고,
로그에는 호출 횟수만 남긴다(`SourceHttp`). 사진 원본이 아니라 카카오가 만든 미리보기(`thumbnail_url`)를 쓰고,
출처 사이트 이름과 원문 주소를 같이 넘겨 화면이 출처를 밝히고 원문으로 보낸다.

검색어는 상호명과 구, 도로명 주소다. 2026-11-10 표본 10곳(프랜차이즈 6곳, 개인 가게 4곳)을 비교했다:
상호명만 찾으면 프랜차이즈는 지점과 상관없이 본사 홍보 사진이 나오고, 동 이름 + 상호명은 다른 브랜드가 섞였다.
주소를 붙이면 그 주소를 적은 블로그 글, 곧 그 지점에 다녀온 글의 사진이 나왔다.

사람 얼굴이 보이는 사진(셀카, 일행 사진)은 뺀다(사용자 결정, 2026-11-10). 화면에 실제로 보이는 미리보기를 받아
YuNet 얼굴 검출(OpenCV, `assets/face_detection_yunet_2023mar.onnx`, MIT)로 보고, 얼굴이 하나라도 있으면 다음 후보로 넘어간다.
같은 표본에서 마스크 쓴 셀카(점수 0.93)와 얼굴이 크게 나온 영상 캡처(0.82)를 잡았다. 인형 얼굴(0.63)도 잡지만 가게 사진이
아니라 빠져도 손해가 없다. 130px 미리보기 속 작은 행인은 못 잡는데, 72px로 보이는 화면에서 알아볼 수 없는 크기다.
받은 이미지는 메모리에서 검사하고 버린다. 받지 못하거나 읽지 못한 사진은 검사할 수 없으니 뺀다.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from places.http import SourceError, SourceHttp

IMAGE_URL = "https://dapi.kakao.com/v2/search/image"

# 블로그 사진 중 그 가게 사진이 아닌 것이 오는 곳(같은 표본으로 확인): 네이버 블로그 이모티콘, 글에 붙인 지도 캡처, 링크 미리보기.
SKIP_HOSTS = frozenset({"storep-phinf.pstatic.net", "simg.pstatic.net", "dthumb-phinf.pstatic.net"})
# 짧은 변이 이보다 작으면 아이콘이나 미리보기 조각이다.
MIN_SIDE = 300
# 화면에 보이는 장수. 걸러 낼 몫을 두고 이만큼 받는다.
PHOTO_LIMIT = 3
FETCH_SIZE = 15

# 미리보기는 카카오가 만든 것만 받는다(서버가 엉뚱한 주소를 부르지 않게). 130px 미리보기라 2MB를 넘을 일이 없다.
THUMBNAIL_HOST_SUFFIX = ".kakaocdn.net"
THUMBNAIL_MAX_BYTES = 2_000_000
FACE_MODEL = Path(__file__).parent / "assets" / "face_detection_yunet_2023mar.onnx"
# 이 점수 이상이면 얼굴이다(YuNet 기본값). 표본에서 사람 얼굴은 0.8 위, 얼굴 아닌 것을 잡은 경우는 0.63이었다.
FACE_SCORE = 0.6

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

    def fetch_thumbnail(self, url: str) -> bytes | None:
        """화면에 보일 미리보기를 받는다. 카카오 CDN의 https 주소가 아니거나 받지 못하면 None."""
        parsed = urlparse(url)
        if parsed.scheme != "https" or not (parsed.hostname or "").endswith(THUMBNAIL_HOST_SUFFIX):
            return None
        try:
            return self._http.request_bytes(self.name, "thumbnail", url, max_bytes=THUMBNAIL_MAX_BYTES)
        except SourceError:
            return None


class FaceDetector:
    """YuNet 얼굴 검출. 모델을 한 번만 읽고(프로세스당 하나), 검출기는 스레드 안전하지 않아 잠근다."""

    def __init__(self, model: Path = FACE_MODEL, score: float = FACE_SCORE) -> None:
        import cv2   # 서버 시작 때가 아니라 처음 쓸 때 읽는다(opencv는 무겁다)
        import numpy as np

        try:   # 모델을 읽을 때 남기는 경고(대상 장치 미지원) 한 줄이 서버 로그를 어지럽히지 않게 오류만 남긴다
            cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
        except AttributeError:
            pass
        self._cv2, self._np = cv2, np
        self._det = cv2.FaceDetectorYN.create(str(model), "", (320, 320), score, 0.3, 5000)
        self._lock = threading.Lock()

    def has_face(self, data: bytes) -> bool | None:
        """얼굴이 하나라도 있으면 True. 이미지로 읽지 못하면 None."""
        img = self._cv2.imdecode(self._np.frombuffer(data, self._np.uint8), self._cv2.IMREAD_COLOR)
        if img is None:
            return None
        h, w = img.shape[:2]
        with self._lock:
            self._det.setInputSize((w, h))
            _, faces = self._det.detect(img)
        return faces is not None and len(faces) > 0


def without_faces(
    candidates: Iterable[PlacePhoto],
    fetch: Callable[[str], bytes | None],
    has_face: Callable[[bytes], bool | None],
    limit: int = PHOTO_LIMIT,
) -> list[PlacePhoto]:
    """후보를 위에서부터 하나씩 받아 얼굴이 없는 것만 limit장 고른다. 얼굴이 있거나, 받지 못하거나, 읽지 못하면 뺀다.
    limit장을 채우면 나머지는 받지 않는다."""
    out: list[PlacePhoto] = []
    for photo in candidates:
        data = fetch(photo.thumbnail_url)
        if data is None or has_face(data) is not False:
            continue
        out.append(photo)
        if len(out) >= limit:
            break
    return out

