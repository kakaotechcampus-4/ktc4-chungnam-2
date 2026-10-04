"""places/place_facts 테이블 접근(데이터 계층). 커밋하지 않는다 — 호출한 쪽(api의 세션 스코프, 적재 스크립트)이 커밋한다.

카카오 응답은 어디에도 쓰지 않는다. 카카오 장소 ID·URL·확인 일자(kakao_*)만 record_kakao_match로 기록한다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Sequence

from geoalchemy2 import Geography, Geometry, WKTElement
from sqlalchemy import cast, func, literal, or_, select, union_all
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from places import matching
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
class PlaceUpsertResult:
    inserted: int
    updated: int
    closed_marked: int      # 이미 있던 장소를 폐업으로 바꾼 수
    closed_ignored: int     # 없던 폐업 장소(신규로 넣지 않는다)


def upsert_places(db: Session, rows: Sequence[PlaceRow]) -> PlaceUpsertResult:
    inserted = updated = closed_marked = closed_ignored = 0
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
            if place is None:
                place = Place(source=r.source, source_id=r.source_id)
                db.add(place)
                existing[(r.source, r.source_id)] = place
                inserted += 1
            else:
                updated += 1
            place.name, place.category, place.address, place.phone = r.name, r.category, r.address, r.phone
            place.geom, place.status = _point(r.lat, r.lng), "open"   # kakao_* 는 건드리지 않는다
        db.flush()
    return PlaceUpsertResult(inserted, updated, closed_marked, closed_ignored)


@dataclass(frozen=True)
class FactUpsertResult:
    upserted: int
    place_not_found: int


def upsert_facts(db: Session, labels: Sequence[LabelRow]) -> FactUpsertResult:
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
            stmt = stmt.on_conflict_do_update(
                index_elements=["place_id", "fact_key"],
                set_={c: stmt.excluded[c] for c in ("value", "confidence", "source_layer", "model_version", "evidence", "label_source", "labeled_at")},
            )
            db.execute(stmt)
            upserted += len(values)
    return FactUpsertResult(upserted, not_found)


# ------------------------------------------------------------------ 공개 함수 뒤의 조회

def find_candidates(db: Session, hint_lat: float, hint_lng: float, category: str, kakao_place_id: str | None) -> list[Candidate]:
    """매칭 후보: 힌트 좌표 반경 안의 영업 중 장소(가까운 순, 상한 MAX_CANDIDATES) + 같은 카카오 ID가 기록된 장소."""
    lat, lng = _lat_lng()
    point = _geog(hint_lat, hint_lng)
    near = db.execute(
        select(Place.id, Place.name, Place.category, Place.kakao_place_id, lat, lng)
        .where(Place.status == "open", Place.category == category,
               func.ST_DWithin(Place.geom, point, matching.MAX_RADIUS_M))
        .order_by(func.ST_Distance(Place.geom, point))
        .limit(matching.MAX_CANDIDATES)
    ).all()
    rows = list(near)
    if kakao_place_id:
        have = {r.id for r in rows}
        rows += [r for r in db.execute(
            select(Place.id, Place.name, Place.category, Place.kakao_place_id, lat, lng)
            .where(Place.status == "open", Place.kakao_place_id == kakao_place_id)
        ).all() if r.id not in have]
    return [Candidate(str(r.id), r.name, r.lat, r.lng, r.category, r.kakao_place_id) for r in rows]


def find_candidates_many(db: Session, hints: Sequence[PlaceHint]) -> list[list[Candidate]]:
    """find_candidates를 힌트 N개에 대해 쿼리 한 번으로 한다(N+1 방지). 힌트마다 가까운 순 상한 MAX_CANDIDATES와
    같은 카카오 ID가 기록된 장소를 돌려준다 — 한 건씩 부른 것과 같은 후보 집합이다.

    반경 판정·정렬은 DB(ST_DWithin·ST_Distance, 타원체)가 한 곳에서 한다. 파이썬은 거리를 다시 계산하지 않는다(#316).
    힌트마다 LIMIT를 건 부분 쿼리를 UNION ALL로 묶어 행 수가 힌트 수 × (MAX_CANDIDATES + 카카오 ID 일치)를 넘지 않는다."""
    if not hints:
        return []
    lat, lng = _lat_lng()
    cols = (Place.id, Place.name, Place.category, Place.kakao_place_id, lat, lng)
    parts = []
    for i, h in enumerate(hints):
        point = _geog(h.lat, h.lng)
        dist = func.ST_Distance(Place.geom, point)
        near = (
            select(*cols, dist.label("dist"))
            .where(Place.status == "open", Place.category == h.category,
                   func.ST_DWithin(Place.geom, point, matching.MAX_RADIUS_M))
            .order_by(dist)
            .limit(matching.MAX_CANDIDATES)
            .subquery()
        )
        parts.append(select(literal(i).label("hint_idx"), literal(0).label("kind"), near))
        if h.kakao_place_id:
            parts.append(
                select(literal(i), literal(1), *cols, literal(0.0))
                .where(Place.status == "open", Place.kakao_place_id == h.kakao_place_id)
            )
    union = union_all(*parts).subquery()
    rows = db.execute(select(union).order_by(union.c.hint_idx, union.c.kind, union.c.dist)).all()
    out: list[list[Candidate]] = [[] for _ in hints]
    seen: list[set] = [set() for _ in hints]
    for r in rows:   # kind 0(반경 안, 가까운 순)이 먼저라 같은 장소가 둘 다 걸리면 앞의 것만 남는다
        if r.id in seen[r.hint_idx]:
            continue
        seen[r.hint_idx].add(r.id)
        out[r.hint_idx].append(Candidate(str(r.id), r.name, r.lat, r.lng, r.category, r.kakao_place_id))
    return out


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
        select(Place.id, lat, lng).where(Place.status == "open", Place.category == category, or_(*circles))
    ).all()
    return [PlaceRef(str(r.id), r.lat, r.lng) for r in rows]


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
