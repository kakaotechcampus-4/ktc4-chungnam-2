"""places 공개 접점 — 다른 모듈은 이 함수들만 부른다(backend/CLAUDE.md). 서비스는 프로세스당 하나."""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
from contextlib import contextmanager
from dataclasses import dataclass, replace
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
    Area, FactLabel, LinkParseResult, PlaceHint, PlaceHours, PlaceInfo, PlaceMatch, PlaceRef, PlaceSearchResult, PlaceSourceInfo,
)
from places.service import PlaceService, to_result
from places.sources.base import PlaceSource
from places.sources.kakao import KakaoPlaceSource
from places.sources.naver import NaverPlaceSource

log = logging.getLogger("pingo.places")
_STATS = CallStats()
search_limiter = SlidingWindowLimiter(settings.places_search_per_min)   # 사용자당 분당 상한, 인메모리
link_limiter = SlidingWindowLimiter(settings.places_search_per_min)     # POST /places/from-link — 검색과 같은 상한, 따로 센다(#474)


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
    """힌트마다 match_place가 성공할지 읽기만 해서 계산한다. 카카오 ID를 기록하지 않는다. 쿼리 한 번(#238).

    주소는 선택 힌트라 핀 생성 요청이 안 보낼 수도 있다(#815 — 화면은 아직 안 보낸다). 그래서 주소 없이도 같은 답이 나올 때만
    True다: 주소가 있어야 구제되는 힌트는 False. 「검색에서 pinnable=true면 핀 생성이 된다」가 주소를 보내든 안 보내든 지켜진다."""
    own = [i for i, h in enumerate(hints) if h.category in matching.OWN_CATEGORIES]
    flags = [False] * len(hints)
    if not own:
        return flags
    with _session(db) as s:
        candidates = repository.find_candidates_many(s, [hints[i] for i in own])
    for i, cands in zip(own, candidates):
        flags[i] = matching.pick_match(hints[i], cands) is not None and (
            hints[i].address is None or matching.pick_match(replace(hints[i], address=None), cands) is not None)
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
        return [_to_search_result(r) for r in _pinnable_rows(s, rows)][:NEAREST_MAX]


@dataclass(frozen=True)
class OwnSearchHit:
    """장소 검색(#822)의 자체 DB 결과 한 건. kakao_place_id는 카카오 결과와 같은 가게인지 가리는 내부 값이라 응답에 싣지 않는다."""

    result: PlaceSearchResult
    kakao_place_id: str | None


TIER_NAME_PREFIX, TIER_NAME_PART, TIER_REST = repository.TIER_NAME_PREFIX, repository.TIER_NAME_PART, repository.TIER_REST
_SEARCH_MAX_PAGES = 5   # pick_match가 거절한 곳이 많아도 limit을 채우려 이어 읽는 최대 페이지 수(페이지 크기 = limit)


_Stage = tuple[int, tuple[float | None, float | None], float | None]   # (계층, 거리 띠, 계층 3에서 뺄 부분 일치 반경)


def _search_stages(near: tuple[float, float] | None) -> list[_Stage]:
    """계약의 순서(docs/api-spec.yaml /places/search 정렬 규칙)를 그대로 내는 읽기 순서.
    좌표가 있으면 지역 구역(30km 안)의 모든 계층이 먼 구역보다 먼저다. 계층 2(부분 일치)는 가까운 순이라 가까운 띠(3km)를 먼저 읽고
    모자랄 때만 다음으로 가도 결과가 같다(가까운 띠의 장소가 어차피 더 앞이다). 다음은 계층 3 한 번으로 부분 일치(3km 밖)와
    주소 일치를 일치 정도 순으로 얻는다 — 비싼 전체 훑기를 구역마다 한 번만 한다. 계층 1은 인덱스라 띠를 나누지 않는다."""
    if near is None:
        return [(TIER_NAME_PREFIX, (None, None), None), (TIER_REST, (None, None), None)]
    close, region = repository.NEAR_RADIUS_M, repository.REGION_RADIUS_M
    return [
        (TIER_NAME_PREFIX, (None, region), None), (TIER_NAME_PART, (None, close), None), (TIER_REST, (None, region), close),
        (TIER_NAME_PREFIX, (region, None), None), (TIER_REST, (region, None), None),
    ]


def search_own_for_query(query: str, near: tuple[float, float] | None, limit: int, *, db: Session | None = None) -> list[OwnSearchHit]:
    """장소 검색(#822, #835)의 자체 DB 몫. 이름 일치 정도 계층(완전·앞부분 > 부분 > 주소만) 순으로, 좌표가 있으면 지역 구역(30km 안)을
    먼저, 먼 구역은 limit에 못 미칠 때만 읽는다(_search_stages). 각 단계 안은 가까운 순 → 정예. 핀으로 만들 수 있는 곳만
    pinnable=True로 최대 limit곳. 단계마다 핀 가능한 곳이 모이거나 후보가 바닥날 때까지(최대 _SEARCH_MAX_PAGES 페이지) 이어 읽는다.
    카카오 값을 쓰지 않는다. 읽기 전용."""
    hits: list[OwnSearchHit] = []
    with _session(db) as s:
        for tier, band, skip in _search_stages(near):
            for page in range(_SEARCH_MAX_PAGES):
                rows = repository.search_open_by_query(s, query, near, limit, offset=page * limit, tier=tier, band=band, skip_part_within=skip)
                hits += [OwnSearchHit(_to_search_result(r), r.kakao_place_id) for r in _pinnable_rows(s, rows)]
                if len(hits) >= limit or len(rows) < limit:
                    break
            if len(hits) >= limit:
                break
    return hits[:limit]


def _pinnable_rows(s: Session, rows: Sequence[repository.NearestRow]) -> list[repository.NearestRow]:
    """핀 생성이 같은 힌트(자기 이름·좌표)로 match_place를 부르므로, 거기서 거절될 곳(동명 점포 등)은 미리 뺀다."""
    if not rows:
        return []
    hints = [PlaceHint(f"own:{r.place_id}", r.name, r.lat, r.lng, r.category) for r in rows]
    candidates = repository.find_candidates_many(s, hints)
    return [r for r, h, c in zip(rows, hints, candidates) if matching.pick_match(h, c) is not None]


def _to_search_result(r: repository.NearestRow) -> PlaceSearchResult:
    return PlaceSearchResult(
        place_id=f"own:{r.place_id}", place_name=r.name[:100], lat=r.lat, lng=r.lng, category=r.category,
        address=r.address[:200] if r.address else None,
        place_source=PlaceSourceInfo(provider=r.source), pinnable=True,
    )


def get_places(place_ids: Sequence[str], *, db: Session | None = None) -> dict[str, PlaceInfo]:
    """이름·좌표·분류·kakao_place_url을 배치로 조회한다. 없는 ID는 키에서 빠진다."""
    with _session(db) as s:
        return repository.get_places(s, place_ids)


def search_nearby_own(
    category: str, areas: Sequence[Area], *, recommendable_only: bool = False, db: Session | None = None,
) -> list[PlaceRef]:
    """반경 안의 영업 중(status='open') 장소의 place_id·좌표. 분류는 음식점·카페·관광지.
    recommendable_only=True면 추천 가능(정예) 장소만 SQL에서 가져온다(#913) — recommend의 후보 풀이 쓴다. 정예 판정은 places 안
    한 곳(repository의 curated 조건)이다."""
    if category not in matching.OWN_CATEGORIES:
        return []
    with _session(db) as s:
        return repository.search_nearby_own(s, category, areas, recommendable_only=recommendable_only)


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
    """place_hours를 배치로 조회한다(#690). 행이 없는 장소는 키에서 뺀다(= 모름). 읽기 전용. 요일 단위 판정은 get_week_open_status."""
    with _session(db) as s:
        return repository.get_hours(s, place_ids)


def week_open_status(hours: dict | None, closed_days: list[str] | None) -> dict[int, str]:
    """요일별 영업 판정(#747) — {0=월 … 6=일: "open"|"closed"|"unknown"}. DB 없이 원본 hours·closed_days를 읽는 쪽이 쓴다. 규칙은 places.core.day_open_status."""
    return core.week_open_status(hours, closed_days)


def get_week_open_status(place_ids: Sequence[str], *, db: Session | None = None) -> dict[str, dict[int, str]]:
    """place_hours를 한 번에 읽어 장소별 요일 판정을 돌려준다(#747). 행이 없는 장소는 키에서 뺀다(= 모름). 읽기 전용."""
    return {pid: core.week_open_status(h.hours, h.closed_days) for pid, h in get_hours(place_ids, db=db).items()}


def open_status_on_weekdays(hours: dict | None, closed_days: list[str] | None, weekdays: Sequence[int]) -> str:
    """여러 요일(여행 기간 등)에서의 영업 여부(#747) — "closed"(모든 요일이 closed) | "open"(하나라도 open) | "unknown".
    DB 없이 원본 hours·closed_days를 읽는 쪽이 쓴다. weekdays는 0=월 … 6=일(date.weekday()). 요일별 규칙은 week_open_status와 같다."""
    return core.open_status_on_weekdays(core.week_open_status(hours, closed_days), weekdays)


def get_open_status_on_weekdays(place_ids: Sequence[str], weekdays: Sequence[int], *, db: Session | None = None) -> dict[str, str]:
    """장소별 open_status_on_weekdays를 place_hours 한 번 조회로(#747). 행이 없는 장소는 키에서 뺀다(= 모름). 읽기 전용."""
    return {pid: core.open_status_on_weekdays(week, weekdays) for pid, week in get_week_open_status(place_ids, db=db).items()}


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


def match_by_name_address(name: str, address: str | None, *, external_id: str | None = None, db: Session | None = None) -> list[PlaceSearchResult]:
    """공유 글의 상호명·주소로 자체 DB 짝 찾기(#946). 짝이 하나로 확실할 때만 1개를, 아니면 빈 목록(가드레일 2 — 체인점·동명·주소 어긋남).
    **주소가 있어야 하고 주소가 같다고 확인된 장소만** 확정한다(주소 없음·비교 불가는 빈 목록 — 후보가 하나뿐이어도 같은 점포라는 근거가 못 된다).
    분류는 음식점·카페·관광지 모두. 규칙은 matching(이름 점수·주소 일치·모호하면 거절)을 그대로 쓰고 후보는 name_norm 인덱스로 좁힌다.
    `external_id`(링크에서 읽은 `kakao:…`·`naver:…` 번호)를 함께 주면 서버가 스스로 확정한 짝을 번호표에 source='hint'로 기록한다(#1048) —
    다음 사람은 같은 링크로 한 번에 찍힌다. 이때만 쓰기가 있고(호출 쪽 트랜잭션에 참여, 커밋하지 않는다) 번호 형식이 틀리면 기록만 건너뛴다.
    주소는 짝 찾기에만 쓴다 — 상호명·주소·번호를 로그·예외에 남기지 않고 저장하지 않는다. 응답 모양은 링크 해석의 matches와 같다."""
    if not name or not name.strip():
        return []
    with _session(db) as s:
        candidates = repository.find_by_name_hint(s, name)
        picked = matching.pick_hint_match(name, address, candidates)
        if picked and external_id:
            m = _EXTERNAL_ID.fullmatch(external_id)
            if m is not None:
                repository.upsert_external_id(s, m.group(1), external_id, picked[0].place_id, "hint", None)
    return [_to_link_match(c) for c in picked]


_EXTERNAL_ID = re.compile(r"(kakao|naver):\d{1,20}")


def _check_external_id(provider: str, external_id: str) -> None:
    m = _EXTERNAL_ID.fullmatch(external_id or "")
    if m is None or m.group(1) != provider:
        raise ValueError("번호 형식이 provider와 맞지 않는다")   # 번호 자체는 메시지에 싣지 않는다


def voter_hash(user_id: str) -> str:
    """번호표 표(`record_external_id(source='user', voter_hash=…)`·`purge_external_id_votes`)에 쓰는 사용자 id의 단방향 해시(#1048).
    HMAC-SHA256 hex 64자 — 키는 SESSION_SECRET에서 용도 문자열로 파생하므로 키 자체는 어디에도 나가지 않고, 같은 사용자는 늘 같은 값이다
    (계정당 한 표, 탈퇴 정리가 같은 값으로 지운다). 해시도 로그·응답에 싣지 않는다. SESSION_SECRET을 바꾸면 기존 표와 이어지지 않는다
    (그 전 표는 탈퇴 정리로 지워지지 않고 남는다 — 표만이고 사용자와 이어 줄 수 없다)."""
    key = hmac.new(settings.session_secret.encode("utf-8"), b"places.external_id_votes.v1", hashlib.sha256).digest()
    return hmac.new(key, user_id.encode("utf-8"), hashlib.sha256).hexdigest()


def record_external_id(provider: str, external_id: str, place_id: str, *, source: str, voter_hash: str | None = None,
                       db: Session | None = None) -> None:
    """카카오·네이버 장소 번호 → 자체 DB 장소 짝을 번호표에 기록한다(#1048). 번호만 저장한다 — 이름·좌표·주소는 저장하지 않는다(#53).
    source='hint'(서버가 상호명·주소로 스스로 확정)는 즉시 신뢰, source='user'(사람이 고른 짝)는 voter_hash(사용자 id의 단방향 해시)당 한 표이고
    서로 다른 2표가 쌓여야 parse_link가 자동 매칭에 쓴다. 같은 번호가 다른 장소에 이어지면 충돌이라 둘 다 자동 매칭에서 빠진다.
    provider·번호·source가 잘못됐거나 user인데 voter_hash가 없으면 ValueError, 없는 place_id면 KeyError — 호출 쪽(pins)이 핀 생성을 막지 않고 넘긴다.
    커밋하지 않는다(db를 넘기면 호출 쪽 트랜잭션에 참여)."""
    if provider not in ("kakao", "naver") or source not in ("hint", "user") or (source == "user" and not voter_hash):
        raise ValueError("provider·source·voter_hash가 계약에 맞지 않는다")
    _check_external_id(provider, external_id)
    with _session(db) as s:
        repository.upsert_external_id(s, provider, external_id, place_id, source, voter_hash)


def purge_external_id_votes(voter_hash: str, *, db: Session | None = None) -> int:
    """탈퇴한 사용자의 번호표 표를 지운다(#1048, auth의 탈퇴 7일 뒤 정리가 부른다). 번호표 행은 공용 데이터라 남긴다. 멱등 — 지운 표 수."""
    if not voter_hash:
        return 0
    with _session(db) as s:
        return repository.purge_external_id_votes(s, voter_hash)


def own_places_by_external_id(external_id: str, *, db: Session | None = None) -> list[Candidate]:
    """번호표가 가리키는 자체 DB 장소(#1048). 신뢰된 단일 행이고 그 장소가 영업 중일 때만 한 곳, 아니면 빈 목록(충돌·표 부족·폐업·번호표에 없음).
    번호 형식이 아니면 빈 목록. 읽기 전용."""
    m = _EXTERNAL_ID.fullmatch(external_id or "")
    if m is None:
        return []
    with _session(db) as s:
        place_id = core.trusted_external_place(repository.external_id_rows(s, m.group(1), external_id))
        return repository.find_open_by_ids(s, [place_id]) if place_id else []


def match_address_candidates(address: str, *, db: Session | None = None) -> list[PlaceSearchResult]:
    """이름이 안 맞아도 같은 도로명주소(건물번호까지)에 영업 중인 음식점·카페·관광지가 **정확히 한 곳**이면 그 하나(#1047).
    자동 확정이 아니라 사람이 「이 장소가 맞나요?」로 확인할 후보다(가드레일 2·4). 같은 주소에 둘 이상(다중 입점 건물)이거나 주소를 비교할 수
    없으면(도로명주소가 아님·건물번호 없음) 빈 목록. 주소는 짝 찾기에만 쓰고 저장·로그하지 않는다. 읽기 전용. 응답 모양은 matches와 같다."""
    term = matching.address_search_term(address or "")
    if term is None:
        return []
    with _session(db) as s:
        candidates = repository.find_by_address_term(s, term)
    return [_to_link_match(c) for c in matching.pick_address_candidate(address, candidates)]


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
        matched_by = None   # 카카오 ID로 기록된 장소는 「링크가 가리키는 장소」 — 호출 쪽(pins)이 link로 표시한다
        if not found:   # 번호표에서 이어진 짝(#1048) — places.kakao_place_id 조회와 합친다
            found = own_places_by_external_id(parsed.kakao_place_id, db=db)[: matching.LINK_MAX_MATCHES]
            matched_by = "external_id" if found else None
        result = LinkParseResult(
            provider="kakao", kakao_place_id=parsed.kakao_place_id, external_id=parsed.kakao_place_id, matched_by=matched_by,
            matches=[_to_link_match(c) for c in found], needs_search_query=not found,
        )
    elif parsed.provider == "naver":
        # 번호뿐인 링크 — 이름·좌표를 모르니 번호표로만 찾는다(#1048). 없으면 호출 쪽이 힌트(상호명·주소)나 검색으로 잇는다
        found = own_places_by_external_id(parsed.external_id, db=db)[: matching.LINK_MAX_MATCHES]
        result = LinkParseResult(
            provider="naver", external_id=parsed.external_id, matched_by="external_id" if found else None,
            matches=[_to_link_match(c) for c in found], needs_search_query=not found,
        )
    else:
        found = []
        address_candidates = None
        split = matching.split_address_and_name(parsed.name_hint or "")
        if split is not None:   # 구글 이름이 「주소 + 상호」면 힌트 경로로(#1047) — 좌표 없이 상호명·주소로 짝을 찾는다
            hinted = match_by_name_address(split[1], split[0], db=db)
            if hinted:
                result = LinkParseResult(provider="google", name_hint=parsed.name_hint, matches=hinted, matched_by="hint", needs_search_query=False)
                log.info("places.link provider=google matches=%d", len(hinted))
                return result
            address_candidates = match_address_candidates(split[0], db=db) or None   # 이름은 안 맞아도 같은 주소의 한 곳 — 사람이 확인할 후보
        if parsed.lat is not None and parsed.lng is not None:
            near = own_places_near(parsed.lat, parsed.lng, matching.LINK_MATCH_RADIUS_M, matching.MAX_CANDIDATES, db=db)
            found = matching.pick_link_matches(parsed.name_hint, near)
        result = LinkParseResult(
            provider="google", name_hint=parsed.name_hint,
            matches=[_to_link_match(c) for c in found], needs_search_query=False,
            address_candidates=None if found else address_candidates,
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
