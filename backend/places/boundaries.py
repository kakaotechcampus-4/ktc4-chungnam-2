"""시·도 경계 파일(#1385) — 지역 판정의 정본은 통계청 2018 시·도 경계 17개 파일 한 벌이다(화면의
`frontend/src/features/map/regionBoundaries/`). 서버는 이 파일을 복제해 새 정본을 만들지 않는다 — 운영용 사본을 읽을 때 내용 해시가
아래 기대값과 같은지 확인해, 화면 정본과 어긋난 파일은 적재를 거절한다. 순수 함수만 둔다(DB 접근은 repository).

파일 모양: `[다각형, ...]`, 다각형은 `[외곽, 구멍, ...]`, 고리는 `[[위도, 경도], ...]`. 해시는 줄바꿈·공백에 흔들리지 않게
`json.dumps(내용, separators=(",", ":"))`의 sha256이다(경계를 고치면 이 표를 같이 고친다 — 모양이 어긋나면 test_sido_boundaries가 잡는다).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

# 통계청 시·도 코드 → places.core.sido와 같은 짧은 이름. 광주(24)·전남(36)은 2026 통합으로 둘 다 "전남광주"(#1059)다
SIDO_BY_CODE = {
    "11": "서울", "21": "부산", "22": "대구", "23": "인천", "24": "전남광주", "25": "대전", "26": "울산", "29": "세종",
    "31": "경기", "32": "강원", "33": "충북", "34": "충남", "35": "전북", "36": "전남광주", "37": "경북", "38": "경남", "39": "제주",
}

EXPECTED_SHA256 = {
    "11": "cb2fc1b816a602f0edff4d8bd4f6642050df395101236fe27f1c0146faea5d64",
    "21": "955f31ee9bf21b0d32f809dd7cd26818cc6b9e70a841ed8d55f201ecacb2f11e",
    "22": "b0ae097156701fd1acce786cae79d507c8deb111709ed6cf0e95e8c29217f66e",
    "23": "ccd940bbc2db248977e6fca549cb1907200d1b4fe2c8240de6b60d48ac2dee24",
    "24": "8ea3d44c92383ff216b5f996b5b5481d2831b6ac588ee64208a25190f07770fd",
    "25": "18f29adacd6c74367346e312a99db937fae6827e81576e8d21c59a0c7488b88b",
    "26": "87b967e73504b2c21a38e34c7f9f16ccd206f301d928466edf2922f4e227adad",
    "29": "0179e4e1bd2360b1a48df2d7dc7653d44c0eecd2933cb8b1548795b8e074b357",
    "31": "2183ff34711dca7520be728ad66f07584640b4a992cf81d31918ab0b90ee5fa8",
    "32": "c6b6cc8edaaeea14ee8900e1d7b026bf2fba6f585f0799e394b70e4b54dae1a4",
    "33": "c36ffa015b1ea817a8f837abefff7fd972d823c074c695bd5a2577814f1a28ec",
    "34": "06fc62c069b0d1ba41071c27ab86fa4e3de023394a3cb108dc70258233ce2d7f",
    "35": "a85d44d3c16fc54c96947bef59090ac3798a54ba73095f667b7abff98e3ecd03",
    "36": "dbdaf22dcd6c74e796547f77e099aa67c9fe1279cf9cbad3726d84dd1d882583",
    "37": "f39916c04abdbba8d4e024cd84c53eaa758eaa82536d3fb3fabb3647a0e144af",
    "38": "56cd03e5f16bff9b3617f34bc5b28de93e0b60e8e08b6e07394ea51a57df0f86",
    "39": "4642b5d637e4c089c00604ead5d58d1acb6d0d61e7249eeb87a5b98d96615bc8",
}


class BoundaryFileError(ValueError):
    """경계 파일이 없거나, 해시가 화면 정본과 다르거나, 모양이 틀렸다 — DB에는 아무것도 쓰지 않는다."""


def content_hash(data) -> str:
    return hashlib.sha256(json.dumps(data, separators=(",", ":")).encode("utf-8")).hexdigest()


def _ring_wkt(ring: list) -> str:
    points = [(float(lat), float(lng)) for lat, lng in ring]
    if len(points) < 3:
        raise BoundaryFileError("고리의 점이 3개보다 적다")
    if points[0] != points[-1]:
        points.append(points[0])   # WKT 고리는 닫혀 있어야 한다
    for lat, lng in points:
        if not (30 <= lat <= 40 and 123 <= lng <= 133):
            raise BoundaryFileError("좌표가 한반도 범위 밖이다")
    return "(" + ",".join(f"{lng} {lat}" for lat, lng in points) + ")"   # WKT는 경도 먼저


def to_wkt(polygons: list) -> str:
    """[[외곽, 구멍...], ...] (위도, 경도) → MULTIPOLYGON WKT(경도, 위도). 구멍은 그대로 안쪽 고리가 된다."""
    if not polygons:
        raise BoundaryFileError("다각형이 없다")
    return "MULTIPOLYGON(" + ",".join("(" + ",".join(_ring_wkt(r) for r in polygon) + ")" for polygon in polygons) + ")"


def read_boundaries(folder: Path) -> list[dict]:
    """폴더의 17개 파일을 읽어 [{code, name, wkt, sha256}]로. 하나라도 없거나 해시가 다르면 BoundaryFileError — 일부만 적재하지 않는다."""
    rows = []
    for code, name in SIDO_BY_CODE.items():
        path = folder / f"{code}.json"
        if not path.is_file():
            raise BoundaryFileError(f"경계 파일이 없다: {path.name}")
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        digest = content_hash(data)
        if digest != EXPECTED_SHA256[code]:
            raise BoundaryFileError(f"{path.name}의 내용이 화면 정본과 다르다(해시 {digest[:12]}… ≠ 기대 {EXPECTED_SHA256[code][:12]}…) — 적재하지 않는다")
        rows.append({"code": code, "name": name, "wkt": to_wkt(data), "sha256": digest})
    return rows
