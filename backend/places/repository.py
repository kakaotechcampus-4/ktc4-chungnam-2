"""places/place_facts 테이블 접근(데이터 계층). 커밋하지 않는다 — 호출한 쪽(api의 세션 스코프, 적재 스크립트)이 커밋한다.

카카오 응답은 어디에도 쓰지 않는다. 카카오 장소 ID·URL·확인 일자(kakao_*)만 record_kakao_match로 기록한다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Sequence

from geoalchemy2 import Geography, Geometry, WKTElement
from sqlalchemy import Float, and_, case, cast, false, func, literal, null, or_, select, union_all, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from places import matching
from places.ingest import HoursRow, LabelRow, PlaceRow
from places.matching import Candidate
from places.models import Place, PlaceFact, PlaceHours
from places.schemas import Area, FactLabel, PlaceHint, PlaceHours as PlaceHoursInfo, PlaceInfo, PlaceRef

_CHUNK = 1000


def _point(lat: float, lng: float) -> WKTElement:
    return WKTElement(f"POINT({lng} {lat})", srid=4326)


def _geog(lat: float, lng: float):
    """ST_DWithin/ST_Distance용 geography 점."""
    return cast(func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326), Geography())


def _lat_lng():
    geom = cast(Place.geom, Geometry())   # geography엔 ST_X/ST_Y가 직접 안 먹는다
    return func.ST_Y(geom).label("lat"), func.ST_X(geom).label("lng")


def _chunks(items: Sequence, size: int = _CHUNK):
    for i in range(0, len(items), size):
        yield items[i : i + size]


# ------------------------------------------------------------------ 적재 (load 스크립트)

@dataclass(frozen=True)
class NearestRow:
    place_id: str
    name: str
    category: str
    address: str | None
    source: str
    lat: float
    lng: float
    kakao_place_id: str | None = None   # 장소 검색(#822)이 카카오 결과와 같은 가게인지 가리는 데만 쓴다. 응답에 싣지 않는다


@dataclass(frozen=True)
class PlaceUpsertResult:
    inserted: int
    updated: int
    closed_marked: int      # 이미 있던 장소를 폐업으로 바꾼 수
    closed_ignored: int     # 없던 폐업 장소(신규로 넣지 않는다)
    category_kept: int = 0  # 이미 다른 분류로 있어 건너뛴 수 — 분류를 덮어쓰지 않는다(#463)
    existing_kept: int = 0  # 이미 있어 손대지 않은 수 — existing="keep"(인허가 커버리지, #507)
    name_changed: int = 0   # 갱신하면서 이름이 바뀐 수
    category_changed: int = 0   # 갱신하면서 분류가 바뀐 수 — existing="overwrite"(정예)에서만 생긴다
    reopened: int = 0       # 폐업이던 장소가 파일에 다시 영업으로 나와 되살린 수(keep에서도 status만 되살린다)


# 이미 있는 (source, source_id)를 어떻게 다루나(#507). 정예 파일은 정예가, 인허가 커버리지는 기존 값이 이긴다.
#   "refresh"   같은 분류면 갱신, 다른 분류면 건너뜀(#463, 기본)
#   "overwrite" 정예 우선 — 이름·분류·주소·좌표를 파일 값으로 갱신(분류가 달라도)
#   "keep"      인허가 커버리지 — 이름·분류·좌표를 건드리지 않는다(신규 행만 넣는다)
EXISTING_MODES = ("refresh", "overwrite", "keep")


def upsert_places(db: Session, rows: Sequence[PlaceRow], *, existing_mode: str = "refresh") -> PlaceUpsertResult:
    if existing_mode not in EXISTING_MODES:
        raise ValueError(f"existing_mode는 {EXISTING_MODES} 중 하나: {existing_mode!r}")
    inserted = updated = closed_marked = closed_ignored = category_kept = existing_kept = name_changed = category_changed = reopened = 0
    for chunk in _chunks(list(rows)):
        keys = {(r.source, r.source_id) for r in chunk}
        existing = {
            (p.source, p.source_id): p
            for p in db.execute(
                select(Place).where(Place.source.in_({k[0] for k in keys}), Place.source_id.in_({k[1] for k in keys}))
            ).scalars()
            if (p.source, p.source_id) in keys
        }
        for r in chunk:
            place = existing.get((r.source, r.source_id))
            if r.status == "closed":
                if place is None:
                    closed_ignored += 1
                elif place.status != "closed":
                    place.status = "closed"
                    closed_marked += 1
                continue
            if place is not None and existing_mode == "keep":
                if place.status == "closed":
                    place.status = "open"   # 닫힌 장소가 파일에 다시 나왔다 — 이름·분류·좌표는 그대로 두고 status만 되살린다
                    reopened += 1
                existing_kept += 1   # 인허가 커버리지는 이미 있는 장소를 건드리지 않는다(#507)
                continue
            if place is not None and existing_mode == "refresh" and place.category != r.category:
                category_kept += 1   # 같은 (source, source_id)가 다른 분류 파일에도 있다 — 음식점을 카페로 덮어쓰지 않는다
                continue
            if place is None:
                place = Place(source=r.source, source_id=r.source_id)
                db.add(place)
                existing[(r.source, r.source_id)] = place
                inserted += 1
            else:
                updated += 1
                reopened += place.status == "closed"
                name_changed += place.name != r.name
                category_changed += place.category != r.category
            place.name, place.category, place.address, place.phone = r.name, r.category, r.address, r.phone
            place.geom, place.status = _point(r.lat, r.lng), "open"   # kakao_* 는 건드리지 않는다
            if existing_mode == "overwrite":
                place.curated = True   # 정예 적재가 켠다. 커버리지(keep)·재계산은 끄지 않는다 — 한 번 true면 유지(#561 후속)
        db.flush()
    return PlaceUpsertResult(inserted, updated, closed_marked, closed_ignored, category_kept, existing_kept, name_changed, category_changed, reopened)


def open_permit_source_ids(db: Session) -> set[str]:
    """--close-missing가 닫을 수 있는 장소: source='permit'이고 정예가 아니며 지금 열려 있는 것의 source_id."""
    return set(db.execute(
        select(Place.source_id).where(Place.source == "permit", Place.curated.is_(False), Place.status == "open")
    ).scalars())


def close_permit_places(db: Session, source_ids: Sequence[str]) -> int:
    """status만 'closed'로 바꾼다(삭제·라벨 삭제 없음). 같은 조건(permit·비정예·열림)을 다시 걸어 정예·다른 출처는 건드리지 않는다."""
    closed = 0
    for chunk in _chunks(list(source_ids)):
        closed += db.execute(
            update(Place)
            .where(Place.source == "permit", Place.curated.is_(False), Place.status == "open", Place.source_id.in_(chunk))
            .values(status="closed")
        ).rowcount
    return closed


@dataclass(frozen=True)
class FactUpsertResult:
    upserted: int
    place_not_found: int
    kept: int = 0   # overwrite=False일 때 이미 있어 건드리지 않은 (장소, fact_key) 수


def upsert_facts(db: Session, labels: Sequence[LabelRow], *, overwrite: bool = True) -> FactUpsertResult:
    """overwrite=True(기본, 정예 파일)는 같은 (장소, fact_key)를 파일 값으로 덮는다. False(인허가 커버리지, #507)는
    이미 있는 라벨을 건드리지 않고 없는 키만 넣는다 — 정예 라벨이 커버리지 값에 밀리지 않는다."""
    kept = 0
    upserted = not_found = 0
    for chunk in _chunks(list(labels)):
        sources = {l.source for l in chunk}
        ids = {l.source_id for l in chunk}
        place_ids = {
            (p.source, p.source_id): p.id
            for p in db.execute(select(Place).where(Place.source.in_(sources), Place.source_id.in_(ids))).scalars()
        }
        values = []
        for l in chunk:
            pid = place_ids.get((l.source, l.source_id))
            if pid is None:
                not_found += 1
                continue
            values.append({
                "place_id": pid, "fact_key": l.fact_key, "value": l.value, "confidence": l.confidence,
                "source_layer": l.source_layer, "model_version": None,
                "evidence": l.evidence, "label_source": l.label_source,
                "labeled_at": l.labeled_at if l.labeled_at is not None else func.now(),
            })
        if values:
            stmt = pg_insert(PlaceFact).values(values)
            if overwrite:
                stmt = stmt.on_conflict_do_update(
                    index_elements=["place_id", "fact_key"],
                    set_={c: stmt.excluded[c] for c in ("value", "confidence", "source_layer", "model_version", "evidence", "label_source", "labeled_at")},
                )
                db.execute(stmt)
                upserted += len(values)
            else:
                written = db.execute(stmt.on_conflict_do_nothing(index_elements=["place_id", "fact_key"])).rowcount
                upserted += written
                kept += len(values) - written
    return FactUpsertResult(upserted, not_found, kept)


# ------------------------------------------------------------------ 공개 함수 뒤의 조회

def find_candidates(db: Session, hint_lat: float, hint_lng: float, category: str, kakao_place_id: str | None) -> list[Candidate]:
    """매칭 후보: 힌트 좌표 반경 안의 영업 중 장소(가까운 순, 상한 MAX_CANDIDATES) + 같은 카카오 ID가 기록된 장소."""
    lat, lng = _lat_lng()
    point = _geog(hint_lat, hint_lng)
    near = db.execute(
        select(Place.id, Place.name, Place.category, Place.kakao_place_id, Place.address, lat, lng,
               func.ST_Distance(Place.geom, point).label("dist"))
        .where(Place.status == "open", Place.category == category,
               func.ST_DWithin(Place.geom, point, matching.MAX_RADIUS_M))
        .order_by(func.ST_Distance(Place.geom, point))
        .limit(matching.MAX_CANDIDATES)
    ).all()
    rows = list(near)
    if kakao_place_id:
        have = {r.id for r in rows}
        rows += [r for r in db.execute(
            select(Place.id, Place.name, Place.category, Place.kakao_place_id, Place.address, lat, lng,
                   cast(null(), Float).label("dist"))   # 반경 밖일 수 있어 거리를 재지 않는다
            .where(Place.status == "open", Place.kakao_place_id == kakao_place_id)
        ).all() if r.id not in have]
    return [Candidate(str(r.id), r.name, r.lat, r.lng, r.category, r.kakao_place_id, r.dist, r.address) for r in rows]


def find_candidates_many(db: Session, hints: Sequence[PlaceHint]) -> list[list[Candidate]]:
    """find_candidates를 힌트 N개에 대해 쿼리 한 번으로 한다(N+1 방지). 힌트마다 가까운 순 상한 MAX_CANDIDATES와
    같은 카카오 ID가 기록된 장소를 돌려준다 — 한 건씩 부른 것과 같은 후보 집합이다.

    반경 판정·정렬·상한은 전부 DB가 한다(ST_DWithin/ST_Distance, 둘 다 타원체) — find_candidates와 같은 기준이라
    파이썬에서 거리를 다시 계산하지 않는다. 힌트마다 `ORDER BY ST_Distance LIMIT`인 SELECT를 UNION ALL로 묶으므로
    돌려받는 행은 최대 (서로 다른 힌트 수 × MAX_CANDIDATES) + 카카오 ID 일치 장소다."""
    if not hints:
        return []
    lat, lng = _lat_lng()
    cols = (Place.id, Place.name, Place.category, Place.kakao_place_id, Place.address, lat, lng)
    keys = list(dict.fromkeys((h.category, h.lat, h.lng) for h in hints))   # 같은 좌표·분류는 한 번만 묻는다
    members = []
    for i, (category, h_lat, h_lng) in enumerate(keys):
        point = _geog(h_lat, h_lng)
        members.append(
            select(literal(i).label("hint_idx"), func.ST_Distance(Place.geom, point).label("dist"), *cols)
            .where(Place.status == "open", Place.category == category,
                   func.ST_DWithin(Place.geom, point, matching.MAX_RADIUS_M))
            .order_by(func.ST_Distance(Place.geom, point), Place.id)
            .limit(matching.MAX_CANDIDATES)
            .subquery().select()
        )
    kakao_ids = {h.kakao_place_id for h in hints if h.kakao_place_id}
    if kakao_ids:
        members.append(
            select(literal(-1).label("hint_idx"), cast(null(), Float).label("dist"), *cols)
            .where(Place.status == "open", Place.kakao_place_id.in_(kakao_ids))
            .subquery().select()
        )
    union = union_all(*members).subquery()
    rows = db.execute(select(union).order_by(union.c.hint_idx, union.c.dist, union.c.id)).all()   # 바깥 정렬이 가까운 순을 다시 보장한다

    near_by_key: dict[tuple[str, float, float], list] = {k: [] for k in keys}
    by_kakao_id: dict[str, list] = {}
    for r in rows:
        if r.hint_idx < 0:
            by_kakao_id.setdefault(r.kakao_place_id, []).append(r)
        else:
            near_by_key[keys[r.hint_idx]].append(r)
    out: list[list[Candidate]] = []
    for h in hints:
        picked = list(near_by_key[(h.category, h.lat, h.lng)])
        have = {r.id for r in picked}
        if h.kakao_place_id:
            picked += [r for r in by_kakao_id.get(h.kakao_place_id, []) if r.id not in have]
        out.append([Candidate(str(r.id), r.name, r.lat, r.lng, r.category, r.kakao_place_id, r.dist, r.address) for r in picked])
    return out


def find_nearby_own(db: Session, lat_: float, lng_: float, radius_m: float, limit: int) -> list[Candidate]:
    """좌표 반경 안의 영업 중 장소를 가까운 순으로(분류 무관). 링크 해석(#474)이 쓴다."""
    lat, lng = _lat_lng()
    point = _geog(lat_, lng_)
    rows = db.execute(
        select(Place.id, Place.name, Place.category, Place.kakao_place_id, Place.address, lat, lng,
               func.ST_Distance(Place.geom, point).label("dist"))
        .where(Place.status == "open", func.ST_DWithin(Place.geom, point, radius_m))
        .order_by(func.ST_Distance(Place.geom, point), Place.id)
        .limit(limit)
    ).all()
    return [Candidate(str(r.id), r.name, r.lat, r.lng, r.category, r.kakao_place_id, r.dist, r.address) for r in rows]


def find_by_kakao_place_id(db: Session, kakao_place_id: str) -> list[Candidate]:
    """이미 이 카카오 장소 ID로 매칭된 영업 중 장소(링크 해석 #474)."""
    lat, lng = _lat_lng()
    rows = db.execute(
        select(Place.id, Place.name, Place.category, Place.kakao_place_id, Place.address, lat, lng)
        .where(Place.status == "open", Place.kakao_place_id == kakao_place_id)
        .order_by(Place.id)
    ).all()
    return [Candidate(str(r.id), r.name, r.lat, r.lng, r.category, r.kakao_place_id, None, r.address) for r in rows]


def record_kakao_match(db: Session, place_id: str, kakao_place_id: str, kakao_place_url: str) -> None:
    """첫 값 유지(#248): 이미 다른 카카오 ID가 기록된 장소는 덮어쓰지 않는다 — 같은 자체 장소를 다른 카카오 ID로
    찍은 사용자가 다른 지도의 링크를 바꾸지 못하게. 같은 ID면 확인 일자만 갱신한다."""
    place = db.get(Place, _uuid(place_id))
    if place is None:
        raise KeyError(place_id)
    if place.kakao_place_id is None:
        place.kakao_place_id, place.kakao_place_url = kakao_place_id, kakao_place_url
    elif place.kakao_place_id != kakao_place_id:
        return
    place.kakao_matched_at = func.now()
    db.flush()


def get_places(db: Session, place_ids: Sequence[str]) -> dict[str, PlaceInfo]:
    ids = [u for u in (_uuid_or_none(p) for p in place_ids) if u is not None]
    if not ids:
        return {}
    lat, lng = _lat_lng()
    rows = db.execute(select(Place.id, Place.name, Place.category, Place.kakao_place_url, Place.source, Place.curated, Place.address, lat, lng)
                      .where(Place.id.in_(ids))).all()
    return {str(r.id): PlaceInfo(str(r.id), r.name, r.lat, r.lng, r.category, r.kakao_place_url, r.source, r.curated, r.address) for r in rows}


def _in_any_area(areas: Sequence[Area]):
    """원 여러 개 중 하나라도 안에 있는가. 원이 겹쳐도 장소는 한 번이다(OR)."""
    return or_(*(func.ST_DWithin(Place.geom, _geog(a.lat, a.lng), a.radius_m) for a in areas))


def search_nearby_own(db: Session, category: str, areas: Sequence[Area]) -> list[PlaceRef]:
    if not areas:
        return []
    lat, lng = _lat_lng()
    # PlaceRef.can_recommend(추천 후보 풀에 넣어도 되는가)는 places.curated 그대로다 — 규칙이 바뀌면 이 쿼리 한 곳만 고친다(#743)
    rows = db.execute(
        select(Place.id, lat, lng, Place.curated).where(Place.status == "open", Place.category == category, _in_any_area(areas))
    ).all()
    return [PlaceRef(str(r.id), r.lat, r.lng, r.curated) for r in rows]


def count_curated(db: Session, category: str, areas: Sequence[Area]) -> int:
    """원들 안의 영업 중 정예 장소 수(#799). 원 처리는 search_nearby_own과 같다."""
    if not areas:
        return 0
    return db.scalar(
        select(func.count()).select_from(Place)
        .where(Place.status == "open", Place.category == category, Place.curated.is_(True), _in_any_area(areas))
    )


def get_ad_places(db: Session, place_ids: Sequence[str], center: tuple[float, float], radius_m: float,
                  categories: Sequence[str]) -> list[dict]:
    """광고용(docs/ads.md 6절). 주어진 ID 중 영업 중·분류 일치·중심 반경 안인 장소. 반경은 idx_places_geom을 탄다."""
    ids = [u for u in (_uuid_or_none(p) for p in place_ids) if u is not None]
    if not ids or not categories:
        return []
    lat, lng = _lat_lng()
    rows = db.execute(
        select(Place.id, Place.name, Place.category, Place.address, lat, lng, Place.kakao_place_id, Place.kakao_place_url)
        .where(Place.id.in_(ids), Place.status == "open", Place.category.in_(list(categories)),
               func.ST_DWithin(Place.geom, _geog(*center), radius_m))
    ).all()
    return [
        {"id": str(r.id), "name": r.name, "category": r.category, "address": r.address, "lat": r.lat, "lng": r.lng,
         "kakao_place_id": r.kakao_place_id, "kakao_place_url": r.kakao_place_url}
        for r in rows
    ]


def curated_counts(db: Session) -> dict[tuple[str, bool], int]:
    """(분류, 정예 여부) → 장소 수. 적재 리포트용(폐업 장소도 센다)."""
    rows = db.execute(select(Place.category, Place.curated, func.count()).group_by(Place.category, Place.curated)).all()
    return {(category, curated): n for category, curated, n in rows}


def find_nearest(db: Session, lat: float, lng: float, category: str | None, radius_m: float, limit: int) -> list[NearestRow]:
    """누른 좌표 반경 안의 영업 중 장소를 가까운 순으로. ST_DWithin이 GiST 인덱스(idx_places_geom)를 탄다.
    좌표는 쿼리 파라미터로만 쓰고 어디에도 남기지 않는다(#473)."""
    rows = db.execute(_nearest_stmt(lat, lng, category, radius_m, limit)).all()
    return [NearestRow(str(r.id), r.name, r.category, r.address, r.source, r.lat, r.lng) for r in rows]


def _nearest_stmt(lat: float, lng: float, category: str | None, radius_m: float, limit: int):
    point = _geog(lat, lng)
    p_lat, p_lng = _lat_lng()
    stmt = (
        select(Place.id, Place.name, Place.category, Place.address, Place.source, p_lat, p_lng,
               func.ST_Distance(Place.geom, point).label("dist"))
        .where(Place.status == "open", func.ST_DWithin(Place.geom, point, radius_m))
        .order_by(func.ST_Distance(Place.geom, point), Place.id)
        .limit(limit)
    )
    if category is not None:
        stmt = stmt.where(Place.category == category)
    return stmt


REGION_RADIUS_M = 30_000.0   # 장소 검색의 지역 구역(#835) — 지도 중심에서 이 안이 먼저다. 값은 docs/api-spec.yaml /places/search 정렬 규칙
NEAR_RADIUS_M = 3_000.0      # 지역 구역 안에서 부분·주소 일치를 먼저 읽는 가까운 띠. 순서는 그대로다(아래 search_open_by_query)

TIER_NAME_PREFIX, TIER_NAME_PART, TIER_REST = 1, 2, 3   # 이름 일치 정도 계층. 1은 완전(1-0)·앞부분(1-1) 일치, 2는 부분 일치, 3(rest)은 부분 일치 + 주소만 일치


def search_open_by_query(
    db: Session, query: str, near: tuple[float, float] | None, limit: int, offset: int = 0,
    *, tier: int, band: tuple[float | None, float | None] = (None, None), skip_part_within: float | None = None,
) -> list[NearestRow]:
    """장소 검색(#822, #835)의 한 계층·한 띠. 영업 중 장소를 이름 일치 정도 계층별로 읽는다.
    계층 1: 정규화한 이름(name_norm)이 검색어로 시작 — 완전 일치가 앞부분 일치보다 앞(인덱스 접두 검색, 2자도 빠르다).
    계층 2: 이름에 검색어가 들었지만 계층 1이 아님(부분 일치).
    계층 3(REST): 계층 2 + 주소에만 들었음(부분 일치가 주소 일치보다 앞). 한 번 훑어 둘을 같이 얻는다.
    skip_part_within=m: 계층 3에서 지도 중심 m 이내의 계층 2(부분 일치)는 뺀다 — 앞서 계층 2로 읽은 것.
    band=(lo, hi): 지도 중심에서 거리가 lo 초과 hi 이하인 장소만(None은 제한 없음, near가 있을 때만 뜻이 있다).
    순서: 계층 1·3은 일치 정도 → 가까운 순 → 정예 → id, 계층 2는 가까운 순 → 정예 → id. 좌표가 없으면 가까운 순 대신 정예 → 이름순.
    좌표는 정렬·거름에만 쓰고 남기지 않는다. offset으로 이어 읽을 수 있다(정렬이 전 순서).
    계층·띠를 어떻게 이어 붙여 계약의 순서를 지키는지는 places.api.search_own_for_query."""
    needle = query.strip()
    if not needle or limit <= 0:
        return []
    nq = matching.normalize_name(needle)   # 숫자·영문·한글만 남아 LIKE 와일드카드가 없다
    escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    in_name = Place.name.ilike(f"%{escaped}%", escape="\\")
    in_address = Place.address.ilike(f"%{escaped}%", escape="\\")
    prefix = Place.name_norm.like(f"{nq}%") if nq else false()
    where = [Place.status == "open", Place.category.in_(matching.OWN_CATEGORIES)]
    if tier == TIER_NAME_PREFIX:
        if not nq:
            return []
        where.append(prefix)
        rank = case((Place.name_norm == nq, 0), else_=1)
    elif tier == TIER_NAME_PART:
        where += [in_name, ~prefix]
        rank = None
    else:
        where += [~prefix, or_(in_name, in_address)]
        rank = case((in_name, 0), else_=1)
    order = [rank] if rank is not None else []
    if near is not None:
        point = _geog(*near)
        lo, hi = band
        if hi is not None:
            where.append(func.ST_DWithin(Place.geom, point, hi))
        if lo is not None:
            where.append(~func.ST_DWithin(Place.geom, point, lo))
        if skip_part_within is not None and tier == TIER_REST:
            where.append(~and_(in_name, func.ST_DWithin(Place.geom, point, skip_part_within)))
        order += [func.ST_Distance(Place.geom, point), Place.curated.desc()]
    else:
        order += [Place.curated.desc(), Place.name.collate("C")]
    p_lat, p_lng = _lat_lng()
    stmt = (
        select(Place.id, Place.name, Place.category, Place.address, Place.source, p_lat, p_lng, Place.kakao_place_id)
        .where(*where).order_by(*order, Place.id).limit(limit).offset(offset)
    )
    return [NearestRow(str(r.id), r.name, r.category, r.address, r.source, r.lat, r.lng, r.kakao_place_id) for r in db.execute(stmt).all()]


def get_facts(db: Session, place_ids: Sequence[str]) -> dict[str, list[FactLabel]]:
    out: dict[str, list[FactLabel]] = {pid: [] for pid in place_ids}
    by_uuid = {u: pid for pid in place_ids if (u := _uuid_or_none(pid)) is not None}
    if not by_uuid:
        return out
    rows = db.execute(
        select(PlaceFact).where(PlaceFact.place_id.in_(list(by_uuid))).order_by(PlaceFact.place_id, PlaceFact.fact_key)
    ).scalars()
    for f in rows:
        out[by_uuid[f.place_id]].append(FactLabel(f.fact_key, f.value, f.confidence))
    return out


def search_by_name_own(db: Session, query: str, category: str | None, limit: int) -> list[dict]:
    """자체 DB 이름 부분 일치(대소문자 무시). status와 무관하게 closed도 돌려준다. 이름순."""
    needle = query.strip()
    if not needle or limit <= 0:
        return []
    escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")   # LIKE 와일드카드는 글자 그대로 찾는다
    stmt = select(Place.id, Place.name, Place.address, Place.category, Place.status).where(Place.name.ilike(f"%{escaped}%", escape="\\"))
    if category is not None:
        stmt = stmt.where(Place.category == category)
    rows = db.execute(stmt.order_by(Place.name.collate("C"), Place.id).limit(limit)).all()
    return [{"id": str(r.id), "name": r.name, "address": r.address, "category": r.category, "status": r.status} for r in rows]


def get_hours(db: Session, place_ids: Sequence[str]) -> dict[str, PlaceHoursInfo]:
    """행이 있는 장소만 돌려준다(행 없음 = 모름). 한 번의 IN 조회."""
    by_uuid = {u: pid for pid in place_ids if (u := _uuid_or_none(pid)) is not None}
    if not by_uuid:
        return {}
    rows = db.execute(select(PlaceHours).where(PlaceHours.place_id.in_(list(by_uuid)))).scalars()
    return {
        by_uuid[h.place_id]: PlaceHoursInfo(h.hours, list(h.closed_days) if h.closed_days is not None else None, h.closed_note, h.hours_note)
        for h in rows
    }


@dataclass(frozen=True)
class HoursUpsertResult:
    upserted: int
    place_not_found: int


def upsert_hours(db: Session, rows: Sequence[HoursRow]) -> HoursUpsertResult:
    """(source, source_id)로 장소를 찾아 place_hours를 upsert한다. 같은 장소는 파일 값으로 갱신, 파일에 없는 장소의 행은 건드리지 않는다."""
    upserted = not_found = 0
    for chunk in _chunks(list(rows)):
        place_ids = {
            (p.source, p.source_id): p.id
            for p in db.execute(
                select(Place).where(Place.source.in_({r.source for r in chunk}), Place.source_id.in_({r.source_id for r in chunk}))
            ).scalars()
        }
        values = {}
        for r in chunk:
            pid = place_ids.get((r.source, r.source_id))
            if pid is None:
                not_found += 1
                continue
            values[pid] = {   # 같은 장소가 파일에 두 번이면 마지막 줄 — 한 INSERT에 같은 키가 두 번 들어가지 않게
                "place_id": pid, "hours": r.hours, "closed_days": r.closed_days,
                "closed_note": r.closed_note, "hours_note": r.hours_note, "updated_at": func.now(),
            }
        if values:
            stmt = pg_insert(PlaceHours).values(list(values.values()))
            db.execute(stmt.on_conflict_do_update(
                index_elements=["place_id"],
                set_={c: stmt.excluded[c] for c in ("hours", "closed_days", "closed_note", "hours_note", "updated_at")},
            ))
            upserted += len(values)
    return HoursUpsertResult(upserted, not_found)


def _uuid(raw: str) -> uuid.UUID:
    return uuid.UUID(raw)


def _uuid_or_none(raw: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(raw)
    except (ValueError, AttributeError, TypeError):
        return None
