"""places/place_facts 테이블 접근(데이터 계층). 커밋하지 않는다 — 호출한 쪽(api의 세션 스코프, 적재 스크립트)이 커밋한다.

카카오 응답은 어디에도 쓰지 않는다. 카카오 장소 ID·URL·확인 일자(kakao_*)만 record_kakao_match로 기록한다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Sequence

from geoalchemy2 import Geography, Geometry, WKTElement
from sqlalchemy import Float, cast, func, literal, null, or_, select, union_all, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from places import core, matching
from places.ingest import LabelRow, PlaceRow
from places.matching import Candidate
from places.models import Place, PlaceFact
from places.schemas import Area, FactLabel, PlaceHint, PlaceInfo, PlaceRef

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


# 이미 있는 (source, source_id)를 어떻게 다루나(#507). 정예 파일은 정예가, 인허가 커버리지는 기존 값이 이긴다.
#   "refresh"   같은 분류면 갱신, 다른 분류면 건너뜀(#463, 기본)
#   "overwrite" 정예 우선 — 이름·분류·주소·좌표를 파일 값으로 갱신(분류가 달라도)
#   "keep"      인허가 커버리지 — 이름·분류·좌표를 건드리지 않는다(신규 행만 넣는다)
EXISTING_MODES = ("refresh", "overwrite", "keep")


def upsert_places(db: Session, rows: Sequence[PlaceRow], *, existing_mode: str = "refresh") -> PlaceUpsertResult:
    if existing_mode not in EXISTING_MODES:
        raise ValueError(f"existing_mode는 {EXISTING_MODES} 중 하나: {existing_mode!r}")
    inserted = updated = closed_marked = closed_ignored = category_kept = existing_kept = name_changed = category_changed = 0
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
                name_changed += place.name != r.name
                category_changed += place.category != r.category
            place.name, place.category, place.address, place.phone = r.name, r.category, r.address, r.phone
            place.geom, place.status = _point(r.lat, r.lng), "open"   # kakao_* 는 건드리지 않는다
        db.flush()
    return PlaceUpsertResult(inserted, updated, closed_marked, closed_ignored, category_kept, existing_kept, name_changed, category_changed)


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
    rows = db.execute(select(Place.id, Place.name, Place.category, Place.kakao_place_url, Place.source, lat, lng).where(Place.id.in_(ids))).all()
    return {str(r.id): PlaceInfo(str(r.id), r.name, r.lat, r.lng, r.category, r.kakao_place_url, r.source) for r in rows}


def search_nearby_own(db: Session, category: str, areas: Sequence[Area]) -> list[PlaceRef]:
    if not areas:
        return []
    lat, lng = _lat_lng()
    circles = [func.ST_DWithin(Place.geom, _geog(a.lat, a.lng), a.radius_m) for a in areas]
    rows = db.execute(
        select(Place.id, lat, lng, Place.can_recommend).where(Place.status == "open", Place.category == category, or_(*circles))
    ).all()
    return [PlaceRef(str(r.id), r.lat, r.lng, r.can_recommend) for r in rows]


@dataclass(frozen=True)
class RecomputeResult:
    counts: dict[tuple[str, bool], int]   # (분류, can_recommend) → 장소 수, 계산한 새 값 기준
    changed: int                          # 값이 바뀐 장소 수(dry_run이면 바뀔 수)


def recompute_can_recommend(db: Session, *, dry_run: bool = False) -> RecomputeResult:
    """전체 장소의 can_recommend를 core 규칙으로 다시 계산해 바뀐 행만 갱신한다. 멱등. 커밋하지 않는다.

    정예 여부는 "출처(label_source)가 없는 라벨 행이 하나라도 있는가"로 가른다 — 정예 납품본은 근거 없는 unknown 행을
    항상 담고, 인허가 커버리지 라벨은 근거 없으면 넣지 않는다(#499). 정예 파일 소속 15,181곳과 양방향 차이 0으로 확인했다
    (places/for_Root.md). 폐업 장소도 계산한다(다시 열릴 때 값이 맞도록)."""
    agg = (
        select(
            PlaceFact.place_id,
            func.count().filter(PlaceFact.confidence == "known").label("known"),
            func.bool_or(PlaceFact.label_source.is_(None)).label("curated"),
        )
        .group_by(PlaceFact.place_id)
        .subquery()
    )
    rows = db.execute(
        select(Place.id, Place.category, Place.can_recommend, func.coalesce(agg.c.known, 0), func.coalesce(agg.c.curated, False))
        .outerjoin(agg, agg.c.place_id == Place.id)
    ).all()
    counts: dict[tuple[str, bool], int] = {}
    to_true: list[uuid.UUID] = []
    to_false: list[uuid.UUID] = []
    for pid, category, current, known, curated in rows:
        new = core.can_recommend(category, known, curated=curated)
        counts[(category, new)] = counts.get((category, new), 0) + 1
        if new != current:
            (to_true if new else to_false).append(pid)
    if not dry_run:
        for ids, value in ((to_true, True), (to_false, False)):
            for chunk in _chunks(ids):
                db.execute(update(Place).where(Place.id.in_(chunk)).values(can_recommend=value))
    return RecomputeResult(counts, len(to_true) + len(to_false))


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


def _uuid(raw: str) -> uuid.UUID:
    return uuid.UUID(raw)


def _uuid_or_none(raw: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(raw)
    except (ValueError, AttributeError, TypeError):
        return None
