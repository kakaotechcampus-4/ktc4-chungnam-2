"""places 공개 접점 — 다른 모듈은 이 함수들만 부른다(backend/CLAUDE.md). 서비스는 프로세스당 하나."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Sequence

import httpx
from sqlalchemy.orm import Session

from common.database import SessionLocal
from common.settings import settings
from places import matching, repository
from places.http import CallStats, SourceHttp
from common.errors import AppError
from places.ratelimit import SlidingWindowLimiter
from places.samples import search_samples
from places.schemas import (
    Area, FactLabel, PlaceHint, PlaceInfo, PlaceMatch, PlaceRef, PlaceSearchResult, ResolvedCoords,
)
from places.service import PlaceService, to_result
from places.sources.base import PlaceSource
from places.sources.kakao import KakaoPlaceSource
from places.sources.naver import NaverPlaceSource

log = logging.getLogger("pingo.places")
_STATS = CallStats()
search_limiter = SlidingWindowLimiter(settings.places_search_per_min)   # 사용자당 분당 상한, 인메모리


def call_counts() -> dict[str, int]:
    """소스별 실제 HTTP 호출 횟수(프로세스 누적)."""
    return _STATS.snapshot()


def build_sources(http: SourceHttp) -> dict[str, PlaceSource]:
    return {
        "kakao": KakaoPlaceSource(http, settings.kakao_rest_api_key),
        "naver": NaverPlaceSource(http, settings.naver_search_client_id, settings.naver_search_client_secret),
    }


@lru_cache(maxsize=1)
def _service() -> PlaceService:
    client = httpx.Client(timeout=settings.places_http_timeout_s)
    http = SourceHttp(client, _STATS, retries=settings.places_http_retries)
    available = build_sources(http)
    ordered = [available[n] for n in settings.places_sources]
    log.info("places.sources order=%s", ", ".join(
        f"{s.name}({'key' if s.is_configured() else 'NO KEY'})" for s in ordered))
    return PlaceService(ordered)


def search_nearby(category: str, areas: Sequence[Area]) -> list[PlaceRef]:
    return _service().search_nearby(category, areas)


def get_raw_facts(place_id: str) -> dict[str, Any]:
    return _service().get_raw_facts(place_id)


def resolve_place(source: str, place_id: str | None, lat: float | None, lng: float | None) -> ResolvedCoords:
    return _service().resolve(source, place_id, lat, lng)


def _is_dev() -> bool:
    return settings.places_mode == "dev"


def check_search_rate(user_id: str) -> None:
    """GET /places/search 사용자당 호출 상한. 카카오 응답 헤더에 쿼터가 없어 서버에서 직접 센다."""
    if not search_limiter.allow(user_id):
        raise AppError("RATE_LIMITED")


def search_by_name(query: str, near: tuple[float, float] | None, limit: int) -> list[PlaceSearchResult]:
    """이름 검색. dev 모드는 카카오를 부르지 않고 고정 샘플 5곳(이름 부분 일치)을 돌려준다."""
    if _is_dev():
        lat, lng = near if near else (None, None)
        return [to_result(p) for p in search_samples(query, lat, lng, limit)]
    return _service().search_by_name(query, near, limit)


# ---- 자체 장소 DB 공개 함수 (docs/architecture.md "places 공개 함수 계약", #189·#190·#195) ----
# 카카오 원자료는 이 함수들의 입출력 어디에도 없다 — kakao_place_id·kakao_place_url만 예외.
# `db`는 계약에 없는 선택 키워드 인자다: 호출한 쪽의 요청 트랜잭션에 참여하려면 넘긴다(특히 record_kakao_match는
# 핀 생성과 같은 커밋이어야 한다). 안 넘기면 짧은 세션을 직접 열고 닫는다(읽기 전용 호출은 그걸로 충분).
# 이 함수들은 커밋하지 않는다 — 넘겨받은 세션은 호출한 쪽이, 직접 연 세션은 여기서 닫기 전에 한 번 커밋한다.

@contextmanager
def _session(db: Session | None):
    if db is not None:
        yield db
        return
    own = SessionLocal()
    try:
        yield own
        own.commit()
    except Exception:
        own.rollback()
        raise
    finally:
        own.close()


def match_place(hint: PlaceHint, *, db: Session | None = None) -> PlaceMatch | None:
    """힌트에 맞는 자체 DB 장소 한 건. 읽기 전용. 반경 300m·후보 수 상한·분류 일치·이름 일치를 모두 만족할 때만,
    확신이 낮으면 None."""
    if hint.category not in matching.OWN_CATEGORIES:
        return None   # 숙소·기타는 자체 DB에 없다
    with _session(db) as s:
        candidates = repository.find_candidates(s, hint.lat, hint.lng, hint.category, hint.kakao_place_id)
    return matching.pick_match(hint, candidates)


def record_kakao_match(place_id: str, kakao_place_id: str, kakao_place_url: str, *, db: Session | None = None) -> None:
    """매칭된 장소에 카카오 장소 ID·URL·확인 일자만 기록한다(핀 생성과 같은 트랜잭션).
    이미 다른 카카오 ID가 있으면 덮어쓰지 않고(첫 값 유지, #248) 같은 ID면 확인 일자만 갱신한다."""
    with _session(db) as s:
        repository.record_kakao_match(s, place_id, kakao_place_id, kakao_place_url)


def pinnable_flags(hints: Sequence[PlaceHint], *, db: Session | None = None) -> list[bool]:
    """힌트마다 match_place가 성공할지 읽기만 해서 계산한다. 카카오 ID를 기록하지 않는다. 쿼리 한 번(#238)."""
    own = [i for i, h in enumerate(hints) if h.category in matching.OWN_CATEGORIES]
    flags = [False] * len(hints)
    if not own:
        return flags
    with _session(db) as s:
        candidates = repository.find_candidates_many(s, [hints[i] for i in own])
    for i, cands in zip(own, candidates):
        flags[i] = matching.pick_match(hints[i], cands) is not None
    return flags


def get_places(place_ids: Sequence[str], *, db: Session | None = None) -> dict[str, PlaceInfo]:
    """이름·좌표·분류·kakao_place_url을 배치로 조회한다. 없는 ID는 키에서 빠진다."""
    with _session(db) as s:
        return repository.get_places(s, place_ids)


def search_nearby_own(category: str, areas: Sequence[Area], *, db: Session | None = None) -> list[PlaceRef]:
    """반경 안의 영업 중(status='open') 장소의 place_id·좌표. 분류는 음식점·카페·관광지."""
    if category not in matching.OWN_CATEGORIES:
        return []
    with _session(db) as s:
        return repository.search_nearby_own(s, category, areas)


def get_facts(place_ids: Sequence[str], *, db: Session | None = None) -> dict[str, list[FactLabel]]:
    """place_facts의 fact_key·value·confidence를 그대로. 라벨이 없으면 빈 리스트. unknown_policy는 호출하는 쪽이 적용한다."""
    with _session(db) as s:
        return repository.get_facts(s, place_ids)
