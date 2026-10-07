"""공공데이터·라벨 파일 → places/place_facts 행으로 바꾸는 순수 변환(DB·파일을 모른다).

적재 셸(places/load.py)이 파일을 읽어 여기 넘기고, 결과를 repository로 upsert한다.
행을 버릴 때는 이유를 센다(Report.skipped) — 조용히 버리지 않는다. 카카오 응답은 어디에도 없다.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Any, Iterable, Iterator, Mapping

# ---------------------------------------------------------------- 공통

KOREA_LAT = (33.0, 39.0)
KOREA_LNG = (124.0, 132.0)
WGS84 = "EPSG:4326"
DEFAULT_PERMIT_CRS = "EPSG:5174"   # 지방행정 인허가 CSV에 흔한 중부원점TM(Bessel). 파일마다 다르면 --crs로 지정한다.


@dataclass
class Report:
    read: int = 0
    accepted: int = 0
    skipped: Counter = field(default_factory=Counter)
    warnings: list[str] = field(default_factory=list)
    accepted_by_type: Counter = field(default_factory=Counter)   # TourAPI contenttypeid별 (parse_tourapi_items만 채운다)
    skipped_by_type: Counter = field(default_factory=Counter)

    def skip(self, reason: str) -> None:
        self.skipped[reason] += 1

    def lines(self) -> list[str]:
        out = [f"읽음 {self.read}행 → 적재 대상 {self.accepted}행, 건너뜀 {sum(self.skipped.values())}행"]
        out += [f"  - {reason}: {n}" for reason, n in self.skipped.most_common()]
        for ctype in sorted(set(self.accepted_by_type) | set(self.skipped_by_type)):
            out.append(f"  [contenttypeid {ctype or '(없음)'}] 받음 {self.accepted_by_type[ctype]} / 건너뜀 {self.skipped_by_type[ctype]}")
        out += [f"  ! {w}" for w in self.warnings]
        return out


@dataclass(frozen=True)
class PlaceRow:
    source: str            # 'permit' | 'tourapi'
    source_id: str
    name: str
    category: str          # 음식점 | 카페 | 관광지
    address: str | None
    phone: str | None
    lat: float
    lng: float
    status: str            # 'open' | 'closed'


def _norm_key(key: str) -> str:
    return re.sub(r"\s+", "", key or "").lower().lstrip("﻿")


def _pick(row: Mapping[str, Any], aliases: Iterable[str]) -> str:
    normalized = {_norm_key(k): v for k, v in row.items()}
    for alias in aliases:
        value = normalized.get(_norm_key(alias))
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return ""


def _to_float(raw: str) -> float | None:
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def in_korea(lat: float, lng: float) -> bool:
    return KOREA_LAT[0] <= lat <= KOREA_LAT[1] and KOREA_LNG[0] <= lng <= KOREA_LNG[1]


@lru_cache(maxsize=8)
def _transformer(crs: str):
    from pyproj import Transformer

    return Transformer.from_crs(crs, WGS84, always_xy=True)


def to_wgs84(x: float, y: float, crs: str = DEFAULT_PERMIT_CRS) -> tuple[float, float]:
    """(x, y) → (lat, lng). 이미 위경도로 보이는 값(-180~180, -90~90)이거나 crs가 WGS84면 그대로 둔다.
    투영좌표는 수십만 단위라 위경도 범위와 겹치지 않으므로 이 판별이 안전하다."""
    if crs.upper() == WGS84 or (abs(x) <= 180 and abs(y) <= 90):
        return y, x
    lng, lat = _transformer(crs).transform(x, y)
    return lat, lng


# ---------------------------------------------------------------- 인허가 (음식점·카페)

PERMIT_ALIASES = {
    "source_id": ("관리번호", "MGTNO"),
    "name": ("사업장명", "BPLCNM"),
    "status": ("영업상태명", "TRDSTATENM"),
    "detail_status": ("상세영업상태명", "DTLSTATENM"),
    "type": ("업태구분명", "UPTAENM"),
    "road_address": ("도로명전체주소", "RDNWHLADDR"),
    "lot_address": ("소재지전체주소", "SITEWHLADDR"),
    "phone": ("소재지전화", "SITETEL"),
    "x": ("좌표정보(x)", "좌표정보x", "X"),
    "y": ("좌표정보(y)", "좌표정보y", "Y"),
}

# 영업 상태 대응. 여기 없는 값은 "알 수 없는 영업상태"로 건너뛰고 건수를 보고한다(조용히 열어두지 않는다).
OPEN_STATUSES = frozenset({"영업/정상", "영업", "정상"})
CLOSED_STATUSES = frozenset({"폐업", "휴업", "취소/말소/만료/정지/중지", "말소", "취소", "정지", "중지", "만료", "폐지"})

# 업태 → 우리 카테고리 대응표. 일반음식점·휴게음식점 업태구분명의 대표 값이다. 표에 없는 업태는 건너뛰고 보고한다
# (유흥·주점류는 일부러 넣지 않았다 — 핀으로 찍는 "음식점"이 아니라고 본다. 데이터 담당과 확정 필요).
CAFE_TYPES = frozenset({"카페", "까페", "커피숍", "다방", "전통찻집", "라이브카페", "제과점영업", "아이스크림", "키즈카페", "커피전문점"})
FOOD_TYPES = frozenset({
    "한식", "중식", "일식", "양식", "분식", "경양식", "김밥(도시락)", "패스트푸드", "뷔페식", "식육(숯불구이)",
    "외국음식전문점(인도,태국등)", "냉면집", "횟집", "복어취급", "탕류(보신용)", "통닭(치킨)", "호프/통닭", "기타", "일반조리판매",
})


def map_permit_category(business_type: str) -> str | None:
    key = re.sub(r"\s+", "", business_type)
    if key in {re.sub(r"\s+", "", t) for t in CAFE_TYPES}:
        return "카페"
    if key in {re.sub(r"\s+", "", t) for t in FOOD_TYPES}:
        return "음식점"
    return None


def permit_status(status: str, detail_status: str = "") -> str | None:
    """'open' | 'closed' | None(모르는 값). 영업상태명을 먼저 보고 비어 있으면 상세영업상태명."""
    for raw in (status, detail_status):
        if raw in OPEN_STATUSES:
            return "open"
        if raw in CLOSED_STATUSES:
            return "closed"
    return None


def parse_permit_rows(
    rows: Iterable[Mapping[str, Any]], *, crs: str = DEFAULT_PERMIT_CRS, seoul_only: bool = True
) -> tuple[list[PlaceRow], Report]:
    report = Report()
    out: list[PlaceRow] = []
    types_without_mapping: Counter = Counter()
    for row in rows:
        report.read += 1
        f = {k: _pick(row, a) for k, a in PERMIT_ALIASES.items()}
        if not f["source_id"] or not f["name"]:
            report.skip("관리번호 또는 사업장명 없음")
            continue
        address = f["road_address"] or f["lot_address"]
        if seoul_only and not address.startswith("서울"):
            report.skip("서울 아님(또는 주소 없음)")
            continue
        status = permit_status(f["status"], f["detail_status"])
        if status is None:
            report.skip(f"알 수 없는 영업상태: {f['status'] or f['detail_status'] or '(비어 있음)'}")
            continue
        category = map_permit_category(f["type"])
        if category is None:
            types_without_mapping[f["type"] or "(비어 있음)"] += 1
            report.skip("업태 대응표에 없음")
            continue
        x, y = _to_float(f["x"]), _to_float(f["y"])
        if x is None or y is None:
            report.skip("좌표 없음")
            continue
        try:
            lat, lng = to_wgs84(x, y, crs)
        except Exception:   # noqa: BLE001 — 변환 실패(잘못된 crs 등)는 그 행의 문제로 센다
            report.skip("좌표 변환 실패")
            continue
        if not in_korea(lat, lng):
            report.skip("좌표가 한국 범위 밖(좌표계 확인)")
            continue
        out.append(PlaceRow("permit", f["source_id"], f["name"], category, address or None, f["phone"] or None, lat, lng, status))
        report.accepted += 1
    if types_without_mapping:
        top = ", ".join(f"{t}({n})" for t, n in types_without_mapping.most_common(10))
        report.warnings.append(f"대응표에 없는 업태(상위): {top}")
    out_of_range = report.skipped.get("좌표가 한국 범위 밖(좌표계 확인)", 0)
    if out_of_range and out_of_range >= report.accepted:   # 대부분이 범위 밖이면 좌표계를 잘못 준 것이다
        report.warnings.append(f"좌표 {out_of_range}행이 한국 범위 밖이다 — --crs가 파일의 좌표계와 맞는지 확인")
    return out, report


# ---------------------------------------------------------------- TourAPI (관광지)

# 관광지(12)·문화시설(14)·쇼핑(38, 납품 파일에는 시장만)은 모두 category '관광지'로 둔다(#379).
TOURAPI_PLACE_TYPES = frozenset({"12", "14", "38"})
TOURAPI_LODGING = "32"
TOURAPI_SEOUL_AREA = "1"
# 서울 행정구역을 감싸는 상자. 주소는 서울인데 좌표가 다른 곳으로 찍힌 항목(예: 경도 127.709)을 거른다.
SEOUL_LAT = (37.41, 37.72)
SEOUL_LNG = (126.73, 127.19)


def in_seoul(lat: float, lng: float) -> bool:
    return SEOUL_LAT[0] <= lat <= SEOUL_LAT[1] and SEOUL_LNG[0] <= lng <= SEOUL_LNG[1]


def extract_tourapi_items(payload: Any) -> list[dict]:
    """API 응답 JSON({response:{body:{items:{item:[...]}}}})이든 item 배열이든 항목 목록으로 편다."""
    if isinstance(payload, list):
        return [i for i in payload if isinstance(i, dict)]
    if isinstance(payload, dict):
        node: Any = payload
        for key in ("response", "body", "items"):
            node = node.get(key, node) if isinstance(node, dict) else node
        if isinstance(node, dict) and "item" in node:
            node = node["item"]
        if isinstance(node, dict):   # item이 한 건이면 dict로 온다
            node = [node]
        if isinstance(node, list):
            return [i for i in node if isinstance(i, dict)]
    return []


def parse_tourapi_items(items: Iterable[Mapping[str, Any]], *, seoul_only: bool = True) -> tuple[list[PlaceRow], Report]:
    report = Report()
    out: list[PlaceRow] = []
    for item in items:
        report.read += 1
        content_type = str(item.get("contenttypeid", "")).strip()
        reason = _tourapi_skip_reason(item, content_type, seoul_only)
        if reason:
            report.skip(reason)
            report.skipped_by_type[content_type] += 1
            continue
        address = _tourapi_address(item)
        lng, lat = _to_float(str(item.get("mapx", ""))), _to_float(str(item.get("mapy", "")))
        out.append(PlaceRow(
            "tourapi", str(item["contentid"]).strip(), str(item["title"]).strip(), "관광지", address or None,
            str(item.get("tel", "")).strip() or None, lat, lng, "open",
        ))
        report.accepted += 1
        report.accepted_by_type[content_type] += 1
    return out, report


def _tourapi_address(item: Mapping[str, Any]) -> str:
    return " ".join(p for p in (str(item.get("addr1", "")).strip(), str(item.get("addr2", "")).strip()) if p)


def _tourapi_skip_reason(item: Mapping[str, Any], content_type: str, seoul_only: bool) -> str | None:
    """받을 수 없는 항목이면 그 이유, 받으면 None."""
    if content_type == TOURAPI_LODGING:
        return "숙박은 받지 않는다"
    if content_type not in TOURAPI_PLACE_TYPES:
        return "관광지·문화시설·쇼핑(contenttypeid=12·14·38) 아님"
    if not str(item.get("contentid", "")).strip() or not str(item.get("title", "")).strip():
        return "contentid 또는 title 없음"
    if seoul_only and str(item.get("areacode", "")).strip() != TOURAPI_SEOUL_AREA and not _tourapi_address(item).startswith("서울"):
        return "서울 아님"
    lng, lat = _to_float(str(item.get("mapx", ""))), _to_float(str(item.get("mapy", "")))
    if lat is None or lng is None or (lat == 0 and lng == 0):
        return "좌표 없음"
    if not in_korea(lat, lng):
        return "좌표가 한국 범위 밖"
    if seoul_only and not in_seoul(lat, lng):
        return "서울 밖 좌표"
    return None


# ---------------------------------------------------------------- 라벨 파일 (place_facts)

PRICE_BUCKETS = frozenset({"low", "mid", "high"})
NOT_LABELS = frozenset({"is_open", "within_radius"})   # 코드 판정이라 place_facts에 없다 (constraints.md)
_KEY_ROW = re.compile(r"^\|\s*`([a-z][a-z0-9_]*)`")


def allowed_fact_keys_from_constraints(markdown: str) -> frozenset[str]:
    """docs/constraints.md 표의 첫 열에서 fact_key를 읽는다. 표가 늘어도 코드는 안 바뀐다(키는 매개변수)."""
    keys = {m.group(1) for line in markdown.splitlines() if (m := _KEY_ROW.match(line))}
    return frozenset(keys - NOT_LABELS)


def is_allowed_fact_key(key: str, allowed: frozenset[str]) -> bool:
    # constraints.md의 "contains_shellfish 등 재료 태그" — 재료 태그는 contains_ 접두로 늘어난다.
    return key in allowed or (key.startswith("contains_") and key not in NOT_LABELS)


@dataclass(frozen=True)
class LabelRow:
    source: str
    source_id: str
    fact_key: str
    value: Any                       # True/False/'low'/'mid'/'high'/None(unknown)
    confidence: str                  # known | unknown
    source_layer: int                # price_bucket은 2(차원 압축), 나머지 3
    labeled_at: datetime | None
    evidence: str | None = None      # 근거 원문(place_facts.evidence, #203) — 가드레일 5의 "이유·출처"에 쓴다
    label_source: str | None = None  # 근거의 종류(license_business_type, 모범음식점 …)


def _parse_bool(raw: str) -> bool | None:
    return {"true": True, "false": False}.get(raw.strip().lower())


def parse_label_rows(rows: Iterable[Mapping[str, Any]], allowed: frozenset[str]) -> tuple[list[LabelRow], Report]:
    report = Report()
    latest: dict[tuple[str, str, str], LabelRow] = {}
    duplicates = 0
    for row in rows:
        report.read += 1
        source, source_id = _pick(row, ("source",)), _pick(row, ("source_id",))
        key, confidence = _pick(row, ("fact_key",)), _pick(row, ("confidence",)).lower()
        raw_value = _pick(row, ("value",))
        if source not in ("permit", "tourapi") or not source_id:
            report.skip("source/source_id 이상")
            continue
        if not is_allowed_fact_key(key, allowed):
            report.skip(f"모르는 fact_key: {key or '(비어 있음)'}")
            continue
        if confidence not in ("known", "unknown"):
            report.skip("confidence가 known/unknown이 아님")
            continue
        if confidence == "unknown":
            value: Any = None
        elif key == "price_bucket":
            if raw_value not in PRICE_BUCKETS:   # 원본 가격 숫자가 들어오면 저장하지 않는다
                report.skip("price_bucket은 low/mid/high만(원본 가격 숫자 거부)")
                continue
            value = raw_value
        else:
            value = _parse_bool(raw_value)
            if value is None:
                report.skip("known인데 value가 true/false가 아님")
                continue
        labeled_at = None
        raw_at = _pick(row, ("labeled_at",))
        if raw_at:
            try:
                labeled_at = datetime.fromisoformat(raw_at)
            except ValueError:
                report.skip("labeled_at이 ISO 날짜가 아님")
                continue
        ident = (source, source_id, key)
        if ident in latest:
            duplicates += 1
        latest[ident] = LabelRow(
            source, source_id, key, value, confidence, 2 if key == "price_bucket" else 3, labeled_at,
            _pick(row, ("evidence",)) or None, _pick(row, ("label_source",)) or None,
        )
    if duplicates:
        report.warnings.append(f"같은 (source, source_id, fact_key)가 {duplicates}번 더 있었다 — 마지막 줄을 썼다")
    out = list(latest.values())
    report.accepted = len(out)
    return out, report


# ---------------------------------------------------------------- 음식점 납품본 (#207)
# 데이터 담당이 큐레이션한 restaurant_seoul_curated.csv(+ _labels.json). 인허가 원본과 달리 좌표가 이미 WGS84 위도/경도이고
# 영업 중인 곳만 담겨 있어 영업상태·좌표 변환·업태→분류 대응이 없다(전부 음식점, source='permit', source_id=관리번호).

CURATED_ALIASES = {
    "source_id": ("관리번호",),
    "name": ("사업장명",),
    "type": ("업태",),
    "address": ("도로명주소", "도로명전체주소", "소재지전체주소"),
    "phone": ("전화번호",),
    "lat": ("위도",),
    "lng": ("경도",),
}
# 유흥·주점류 업태. 지금은 기본으로 적재하고(--exclude-bars로 제외), 제외 여부는 루트 결정 대기(#207).
BAR_TYPES = frozenset({"정종/대포집/소주방", "감성주점"})


# 카페 납품본(cafe_seoul_curated.csv, #266)의 업태 8종 — 전부 분류 '카페'. 대응표에 없는 업태는 건너뛰고 건수를 보고한다.
CURATED_CAFE_TYPES = frozenset({"커피숍", "제과점영업", "까페", "다방", "전통찻집", "라이브카페", "키즈카페", "떡카페"})


def parse_curated_rows(
    rows: Iterable[Mapping[str, Any]], *, exclude_bars: bool = False, seoul_only: bool = True,
    category: str = "음식점", allowed_types: frozenset[str] | None = None,
) -> tuple[list[PlaceRow], Report]:
    """allowed_types를 주면 그 업태만 적재하고 나머지(빈 업태 포함)는 '모르는 업태'로 건너뛴다. 안 주면 업태를 가리지 않는다."""
    report = Report()
    out: list[PlaceRow] = []
    seen_bars = 0
    for row in rows:
        report.read += 1
        f = {k: _pick(row, a) for k, a in CURATED_ALIASES.items()}
        if not f["source_id"] or not f["name"]:
            report.skip("관리번호 또는 사업장명 없음")
            continue
        if seoul_only and not f["address"].startswith("서울"):
            report.skip("서울 아님(또는 주소 없음)")
            continue
        if f["type"] in BAR_TYPES:
            seen_bars += 1
            if exclude_bars:
                report.skip(f"유흥·주점류 제외(--exclude-bars): {f['type']}")
                continue
        if allowed_types is not None and f["type"] not in allowed_types:
            report.skip(f"모르는 업태: {f['type'] or '(비어 있음)'}")
            continue
        lat, lng = _to_float(f["lat"]), _to_float(f["lng"])
        if lat is None or lng is None:
            report.skip("좌표 없음")
            continue
        if not in_korea(lat, lng):
            report.skip("좌표가 한국 범위 밖")
            continue
        if not f["type"]:
            report.warnings.append(f"업태가 비어 있는 행을 {category}로 적재했다: {f['source_id']}")
        out.append(PlaceRow("permit", f["source_id"], f["name"], category, f["address"] or None, f["phone"] or None, lat, lng, "open"))
        report.accepted += 1
    if seen_bars:
        verb = "제외했다" if exclude_bars else "그대로 적재 대상에 포함했다"
        report.warnings.append(f"유흥·주점류 업태(정종/대포집/소주방, 감성주점) {seen_bars}행을 {verb} — 루트 결정 대기")
    return out, report


def parse_cafe_rows(rows: Iterable[Mapping[str, Any]], *, seoul_only: bool = True) -> tuple[list[PlaceRow], Report]:
    """카페 납품본: 분류 '카페', source='permit', source_id=관리번호. 업태 8종 밖·좌표 없는 행은 건너뛰고 센다."""
    return parse_curated_rows(rows, seoul_only=seoul_only, category="카페", allowed_types=CURATED_CAFE_TYPES)


CURATED_PLACE_ID_PREFIXES = ("rest_", "cafe_")   # 음식점·카페 납품본 라벨 JSON의 place_id 접두어(CSV 쪽은 접두어가 이미 없다)


def curated_labels_to_rows(entries: Iterable[Mapping[str, Any]]) -> Iterator[dict[str, str]]:
    """납품본 라벨 JSON → parse_label_rows가 읽는 CSV 행 형식. 장소마다 place_id(rest_|cafe_<관리번호>)와
    labels{fact_key: {value: "true|false|unknown"(문자열), evidence, source}}가 있다. unknown은 confidence=unknown(값 없음)."""
    for entry in entries:
        place_id = str(entry.get("place_id", ""))
        prefix = next((p for p in CURATED_PLACE_ID_PREFIXES if place_id.startswith(p)), None)
        source_id = place_id[len(prefix):] if prefix else ""
        for key, label in (entry.get("labels") or {}).items():
            raw = str((label or {}).get("value", "")).strip()
            unknown = raw.lower() == "unknown" or raw == ""
            yield {
                "source": "permit" if source_id else "",   # source_id가 없으면 parse_label_rows가 "source/source_id 이상"으로 센다
                "source_id": source_id,
                "fact_key": key,
                "value": "" if unknown else raw,
                "confidence": "unknown" if unknown else "known",
                "evidence": str((label or {}).get("evidence") or ""),
                "label_source": str((label or {}).get("source") or ""),
            }
