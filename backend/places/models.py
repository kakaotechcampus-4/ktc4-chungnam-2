"""
이 모듈이 소유하는 테이블만 정의한다(docs/data-model.md "places / place_facts", backend/CLAUDE.md).

places는 자체 장소 DB다(#53). 이름·좌표·주소는 인허가 공공데이터와 TourAPI에서만 온다 — 카카오 응답은
저장하지 않는다. 카카오 장소 ID·URL·확인 일자(kakao_*)만 예외(저장 허용 범위).
"""

import uuid
from datetime import datetime

from geoalchemy2 import Geography, Geometry
from sqlalchemy import Boolean, CheckConstraint, Computed, DateTime, Index, Enum, ForeignKey, SmallInteger, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from common import categories
from common.database import Base

# pins.category enum("category")과 따로 둔다 — 자체 DB는 핀을 만들 수 있는 분류만 담는다(common/categories.py, #280).
PlaceCategory = Enum(*categories.pinnable(), name="place_category")
PlaceSourceEnum = Enum("permit", "tourapi", name="place_source")
PlaceStatus = Enum("open", "closed", name="place_status")
FactConfidence = Enum("known", "unknown", name="fact_confidence")


# 이름의 비교용 정규형(#835) — matching.normalize_name과 같은 규칙: 괄호 안·공백·기호를 지우고 소문자.
# 생성 열이라 적재 코드는 쓰지 않는다. 장소 검색의 완전·앞부분 일치가 이 열의 접두 검색(text_pattern_ops btree)을 탄다.
NAME_NORM_SQL = (
    r"lower(regexp_replace(regexp_replace(name, '[(\[（][^)\]）]*[)\]）]', '', 'g'), '[^0-9a-zA-Z가-힣]', '', 'g'))"
)


class Place(Base):
    __tablename__ = "places"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(PlaceSourceEnum, nullable=False)
    source_id: Mapped[str] = mapped_column(String, nullable=False)   # 그 데이터셋의 관리번호/콘텐츠 ID
    name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(PlaceCategory, nullable=False)
    address: Mapped[str | None] = mapped_column(String, nullable=True)
    name_norm: Mapped[str] = mapped_column(Text, Computed(NAME_NORM_SQL, persisted=True))
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    # 좌표계가 위경도가 아니면 적재 시 변환해 넣는다. 좌표 없는 행은 적재하지 않으므로 NOT NULL.
    # GiST 인덱스는 geoalchemy2가 spatial_index(기본 True)로 만든다 — idx_places_geom.
    geom = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    status: Mapped[str] = mapped_column(PlaceStatus, nullable=False, server_default="open")
    # 정예(사람이 직접 조사·납품한 데이터)인가 — `--authoritative` 적재가 켜고 한 번 true면 끄지 않는다. docs/data-model.md places 절.
    curated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # 사용자가 검색해서 고를 때 한 건씩 매칭한 결과. 카카오 응답의 이름·주소·좌표는 저장하지 않는다.
    kakao_place_id: Mapped[str | None] = mapped_column(String, nullable=True)
    kakao_place_url: Mapped[str | None] = mapped_column(String, nullable=True)
    kakao_matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_places_source_source_id"),
        Index("idx_places_name_norm", "name_norm", postgresql_ops={"name_norm": "text_pattern_ops"}),
    )


class PlaceFact(Base):
    """place_facts는 캐시가 아니다 — TTL로 만료시키지 않는다. 다시 라벨링하면 덮어쓴다(labeled_at 갱신)."""

    __tablename__ = "place_facts"

    place_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("places.id", ondelete="CASCADE"), primary_key=True
    )
    fact_key: Mapped[str] = mapped_column(String, primary_key=True)
    value = mapped_column(JSONB(none_as_null=True), nullable=True)   # boolean/enum. confidence=unknown이면 NULL
    confidence: Mapped[str] = mapped_column(FactConfidence, nullable=False)
    source_layer: Mapped[int] = mapped_column(SmallInteger, nullable=False)   # architecture.md 3층 모델
    model_version: Mapped[str | None] = mapped_column(String, nullable=True)  # v2 모델 라벨링부터
    # 라벨의 근거 원문과 종류(#203) — 가드레일 5의 "이유·출처". 근거가 없는 라벨(예: unknown)은 NULL.
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    label_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    labeled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (CheckConstraint("source_layer IN (1, 2, 3)", name="ck_place_facts_source_layer"),)


class PlaceHours(Base):
    """영업시간·휴무일(#690). 칸이 없으면 행이 없다 = 모름. 모양은 docs/data-model.md place_hours 절."""

    __tablename__ = "place_hours"

    place_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("places.id", ondelete="CASCADE"), primary_key=True
    )
    hours = mapped_column(JSONB(none_as_null=True), nullable=True)   # {"월": [["11:00","21:00"]], …} 요일 7개, 빈 목록 = 휴무, "26:00" = 다음 날 02:00
    closed_days = mapped_column(ARRAY(Text), nullable=True)           # 매주 쉬는 요일. [] = 연중무휴, NULL = 모름
    closed_note: Mapped[str | None] = mapped_column(Text, nullable=True)   # 표시용 원문 — 판단에 쓰지 않는다
    hours_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PlaceExternalId(Base):
    """카카오·네이버 장소 번호 → 자체 DB 장소(#1048). 번호만 저장한다 — 이름·좌표·주소는 저장하지 않는다(#53). 모양은 docs/data-model.md."""

    __tablename__ = "place_external_ids"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String, nullable=False)       # 'kakao' | 'naver'
    external_id: Mapped[str] = mapped_column(String, nullable=False)    # 예 'naver:1412566798'
    place_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("places.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)         # 'hint' = 서버가 스스로 확정 | 'user' = 사람이 고른 짝(표 2개 이상이어야 신뢰)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("provider", "external_id", "place_id", name="uq_place_external_ids_pair"),
        CheckConstraint("provider IN ('kakao', 'naver')", name="ck_place_external_ids_provider"),
        CheckConstraint("source IN ('hint', 'user')", name="ck_place_external_ids_source"),
        Index("idx_place_external_ids_lookup", "provider", "external_id"),
    )


class PlaceExternalIdVote(Base):
    """'user' 짝의 확인 표(#1048). voter_hash는 사용자 id의 단방향 해시 — id를 그대로 두지 않는다. 계정당 한 표. 탈퇴 정리가 지운다."""

    __tablename__ = "place_external_id_votes"

    external_id_row: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("place_external_ids.id", ondelete="CASCADE"), primary_key=True
    )
    voter_hash: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("idx_place_external_id_votes_voter", "voter_hash"),)


class SidoBoundary(Base):
    """시·도 경계(#1385) — 지역 판정의 정본(places.api.sido_at, circle_outside_region). 통계청 2018 시·도 17개 파일을
    `python -m places.load boundaries`가 넣는다. 전남(36)·광주(24)는 둘 다 name이 "전남광주"다. 표가 비면 가장 가까운 장소 주소로 판정하던 방식으로 돌아간다."""

    __tablename__ = "sido_boundaries"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    geom = mapped_column(Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=True), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String, nullable=False)
