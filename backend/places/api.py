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
from places import core, linkfetch, linkparse, matching, repository
from places.http import CallStats, SourceHttp
from common.errors import AppError
from places.ratelimit import SlidingWindowLimiter
from places.samples import search_samples
from places.matching import Candidate
from places.schemas import (
    Area, FactLabel, LinkParseResult, PlaceHint, PlaceHours, PlaceInfo, PlaceMatch, PlaceRef, PlaceSearchResult, PlaceSourceInfo, ResolvedCoords,
)
from places.service import PlaceService, to_result
from places.sources.base import PlaceSource
from places.sources.kakao import KakaoPlaceSource
from places.sources.naver import NaverPlaceSource

log = logging.getLogger("pingo.places")
_STATS = CallStats()
search_limiter = SlidingWindowLimiter(settings.places_search_per_min)   # 사용자당 분당 상한, 인메모리
link_limiter = SlidingWindowLimiter(settings.places_search_per_min)     # POST /places/from-link — 검색과 같은 상한, 따로 센다(#474)


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
    이미 다른 카카오 ID가 있으면 덮어쓰지 않고(첫 값 유지, #248) 같은 ID면 확인 일자만 갱신한다.
    없는 place_id면 KeyError다(호출 쪽이 매칭된 id만 넘긴다)."""
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


NEAREST_RADIUS_M = 100.0   # GET /places/nearest 반경(#473)
NEAREST_MAX = 5
_NEAREST_FETCH = 10        # pinnable이 아닌 곳을 걸러 내도 NEAREST_MAX를 채우도록 조금 더 읽는다


def nearest_own_places(lat: float, lng: float, category: str | None, *, db: Session | None = None) -> list[PlaceSearchResult]:
    """누른 좌표 100m 안의 자체 DB 장소를 가까운 순 최대 5곳. 핀으로 만들 수 있는(pinnable) 곳만, 없으면 빈 배열.
    카카오 값을 쓰지 않고 좌표를 저장·로깅하지 않는다. 읽기 전용."""
    if category is not None and category not in matching.OWN_CATEGORIES:
        return []   # 숙소·기타는 자체 DB에 없다
    with _session(db) as s:
        rows = repository.find_nearest(s, lat, lng, category, NEAREST_RADIUS_M, _NEAREST_FETCH)
        if not rows:
            return []
        # 핀 생성이 같은 힌트(자기 이름·좌표)로 match_place를 부르므로, 거기서 거절될 곳(동명 점포 등)은 미리 뺀다
        hints = [PlaceHint(f"own:{r.place_id}", r.name, r.lat, r.lng, r.category) for r in rows]
        candidates = repository.find_candidates_many(s, hints)
    flags = [matching.pick_match(h, c) is not None for h, c in zip(hints, candidates)]
    return [
        PlaceSearchResult(
            place_id=f"own:{r.place_id}", place_name=r.name[:100], lat=r.lat, lng=r.lng, category=r.category,
            address=r.address[:200] if r.address else None,
            place_source=PlaceSourceInfo(provider=r.source), pinnable=True,
        )
        for r, ok in zip(rows, flags) if ok
    ][:NEAREST_MAX]


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


def count_curated(category: str, areas: Sequence[Area], *, db: Session | None = None) -> int:
    """원들 안의 영업 중(status='open') 정예(curated) 장소 수(#799). 원 처리는 search_nearby_own과 같고 쿼리 한 번이다.
    음식점·카페·관광지 밖이거나 원이 없으면 0. 읽기 전용."""
    if category not in matching.OWN_CATEGORIES:
        return 0
    with _session(db) as s:
        return repository.count_curated(s, category, areas)


# ---- 동네와 카카오맵 검색 링크 (#798, #799) — 카카오를 부르지 않고 저장하지 않는다. 규칙은 places.core 한 곳 ----

def neighborhood(address: str | None) -> str | None:
    """주소 → "{시·군·구} {괄호 안 동(읍·면)}"(예 "해운대구 우동"). 괄호가 없으면 시·군·구까지, 주소가 없으면 None."""
    return core.neighborhood(address)


def kakao_search_url(query: str) -> str:
    """카카오맵 검색 링크 "https://map.kakao.com/link/search/" + URL 인코딩한 검색어. 이 형식을 다른 곳에서 다시 적지 않는다."""
    return core.kakao_search_url(query)


def place_link(place: PlaceInfo) -> str | None:
    """get_places 결과 하나의 「카카오맵에서 보기」 링크. 기록된 카카오 장소 URL이 있으면 그것, 없으면 "{이름} {동네}"
    검색 링크(동네가 없으면 이름만). 이름이 없으면 None. recommend(결과 카드)와 pins(핀 상세)가 부른다."""
    return core.place_link(place.name, place.address, place.kakao_place_url)


def get_ad_places(db: Session, *, place_ids: Sequence[str], center: tuple[float, float], radius_m: float,
                  categories: Sequence[str]) -> list[dict]:
    """추천 탭 광고용(docs/ads.md 5·6절, #645). 주어진 place_id 중 status=open, category in categories,
    center(lat, lng)에서 radius_m 안인 장소만 {id, name, category, address, lat, lng, kakao_place_id, kakao_place_url}로.
    없는 ID·형식이 틀린 ID는 빠진다. 읽기 전용, 커밋하지 않는다."""
    return repository.get_ad_places(db, place_ids, center, radius_m, categories)


def search_own_by_name(db: Session, *, query: str, category: str | None = None, limit: int = 20) -> list[dict]:
    """자체 DB places에서 이름 부분 일치(대소문자 무시, #674). status와 무관하게 돌려준다(closed도 — 광고 등록에서 고르지 않도록 보여야 한다).
    [{id, name, address, category, status}] 이름순. 읽기 전용, 커밋하지 않는다. 카카오를 부르지 않는다."""
    return repository.search_by_name_own(db, query, category, limit)


def get_facts(place_ids: Sequence[str], *, db: Session | None = None) -> dict[str, list[FactLabel]]:
    """place_facts의 fact_key·value·confidence를 그대로. 라벨이 없으면 빈 리스트. unknown_policy는 호출하는 쪽이 적용한다."""
    with _session(db) as s:
        return repository.get_facts(s, place_ids)


def get_hours(place_ids: Sequence[str], *, db: Session | None = None) -> dict[str, PlaceHours]:
    """place_hours를 배치로 조회한다(#690). 행이 없는 장소는 키에서 뺀다(= 모름). 읽기 전용. 판정은 places.core.is_open_on."""
    with _session(db) as s:
        return repository.get_hours(s, place_ids)


def week_open_status(hours: dict | None, closed_days: list[str] | None) -> dict[int, str]:
    """요일별 영업 판정(#747) — {0=월 … 6=일: "open"|"closed"|"unknown"}. DB 없이 원본 hours·closed_days를 읽는 쪽이 쓴다. 규칙은 places.core.day_open_status."""
    return core.week_open_status(hours, closed_days)


def get_week_open_status(place_ids: Sequence[str], *, db: Session | None = None) -> dict[str, dict[int, str]]:
    """place_hours를 한 번에 읽어 장소별 요일 판정을 돌려준다(#747). 행이 없는 장소는 키에서 뺀다(= 모름). 읽기 전용."""
    return {pid: core.week_open_status(h.hours, h.closed_days) for pid, h in get_hours(place_ids, db=db).items()}


# ---- 지도 링크 해석 (POST /places/from-link, #474) ----
# parse-only: 아무것도 저장하지 않는다. 링크의 좌표·이름은 자체 DB를 찾는 데만 쓰고 응답·로그에 싣지 않는다.

def check_link_rate(user_id: str) -> None:
    if not link_limiter.allow(user_id):
        raise AppError("RATE_LIMITED")


@lru_cache(maxsize=1)
def _link_client() -> httpx.Client:
    return linkfetch.make_client()


def own_places_near(lat: float, lng: float, radius_m: float, limit: int, *, db: Session | None = None) -> list[Candidate]:
    """좌표 반경 안의 영업 중 자체 DB 장소(가까운 순). 읽기 전용."""
    with _session(db) as s:
        return repository.find_nearby_own(s, lat, lng, radius_m, limit)


def own_places_by_kakao_id(kakao_place_id: str, *, db: Session | None = None) -> list[Candidate]:
    """이미 이 카카오 장소 ID로 매칭된 영업 중 자체 DB 장소. 읽기 전용."""
    with _session(db) as s:
        return repository.find_by_kakao_place_id(s, kakao_place_id)


def parse_link(url: str, *, db: Session | None = None) -> LinkParseResult:
    """구글맵·카카오맵 링크 → 단서. 허용 호스트가 아니면 LINK_NOT_SUPPORTED, 단축 링크를 못 열었거나 장소를 못 찾으면 LINK_UNRESOLVED."""
    parts = linkparse.split_url(url)
    final = parts.geturl()
    shortened = linkparse.is_short_host((parts.hostname or "").lower().rstrip("."))
    if shortened:
        try:
            final = linkfetch.follow_short_link(final, client=_link_client())
        except linkfetch.LinkFetchError as exc:
            log.info("places.link 단축 링크 해석 실패: %s", exc)   # 링크 주소는 남기지 않는다
            raise AppError("LINK_UNRESOLVED") from exc
    parsed = linkparse.parse_resolved(final)
    if parsed is None:
        raise AppError("LINK_UNRESOLVED" if shortened else "LINK_NOT_SUPPORTED")

    if parsed.provider == "kakao":
        found = own_places_by_kakao_id(parsed.kakao_place_id, db=db)[: matching.LINK_MAX_MATCHES]
        result = LinkParseResult(
            provider="kakao", kakao_place_id=parsed.kakao_place_id,
            matches=[_to_link_match(c) for c in found], needs_search_query=not found,
        )
    else:
        found = []
        if parsed.lat is not None and parsed.lng is not None:
            near = own_places_near(parsed.lat, parsed.lng, matching.LINK_MATCH_RADIUS_M, matching.MAX_CANDIDATES, db=db)
            found = matching.pick_link_matches(parsed.name_hint, near)
        result = LinkParseResult(
            provider="google", name_hint=parsed.name_hint,
            matches=[_to_link_match(c) for c in found], needs_search_query=False,
        )
    log.info("places.link provider=%s matches=%d", result.provider, len(result.matches))
    return result


def _to_link_match(c: Candidate) -> PlaceSearchResult:
    """핀 생성 요청에 그대로 되돌려 보낼 모양. place_id는 기록된 카카오 ID가 있으면 그것, 없으면 `own:<id>`(카카오 ID로 기록되지 않는다)."""
    return PlaceSearchResult(
        place_id=c.kakao_place_id or f"own:{c.place_id}",
        place_name=c.name[:100], lat=c.lat, lng=c.lng, category=c.category,
        address=c.address[:200] if c.address else None, pinnable=True,
    )
