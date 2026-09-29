"""
이 모듈이 소유하는 테이블 전체(docs/data-model.md 166-229행) — #108 착수 시점에
`recommend_runs`/`candidates`는 이미 있었고(PR #71 멘토 리뷰 대응, publish_candidate 슬라이스),
이번에 `evidence_lines`/`regions`/`exclusions`를 추가한다.

**data-model.md 대비 실제 구현 차이 (for_Root.md에 정리)**:
- `candidates.lat`/`lng` — 기존 세션이 이미 추가(위 이유 그대로 유지). `region_id`는 이제
  `regions` 테이블이 생겼으므로 FK를 건다(이전엔 컬럼만 있었다).
- `regions`에 `label`(String)·`center_lat`/`center_lng`/`radius_m`(Float/Integer)을 추가하고
  `geom geography` 컬럼은 두지 않았다. data-model.md는 `geom`만 규정하지만, api-spec.yaml의
  `Region` 스키마가 `label`을 요구하는데 리버스 지오코딩(장소명 조회)을 해줄 `places`가 없어
  "N번째 지역" 같은 라벨을 만들 수조차 없다 — 대신 병합된 원(중심+반경)을 평범한 float
  컬럼으로 저장한다(PostGIS geography 대신). `candidates.lat/lng`와 같은 종류의 차원 압축
  결정이다(for_Root.md에 명시적으로 보고 — geom 컬럼을 아예 안 둔 건 이전 세션의 "컬럼만
  더 둔다"보다 한 단계 더 나간 이탈이라 루트 확인이 더 필요하다).

category/status는 pins.models의 동명 개념과 값이 같지만, 별도 Postgres ENUM 타입 이름
(recommend_category/recommend_run_status/...)을 쓴다 — recommend/CLAUDE.md "pins.models를
직접 import하지 않는다"를 지키면서 같은 이름의 enum 타입을 같은 metadata에 두 번 만들려는
충돌도 피한다.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from common.database import Base

Category = Enum("음식점", "카페", "숙소", "관광지", name="recommend_category")
RunStatus = Enum(
    "collecting_evidence", "awaiting_region_confirm", "executing", "done", "failed",
    name="recommend_run_status",
)
EvidenceSource = Enum("reaction", "manual", name="recommend_evidence_source")
EvidenceBadge = Enum("required", "preferred", "reference", name="recommend_evidence_badge")
ExclusionReason = Enum("proposed", "dismissed", name="recommend_exclusion_reason")


class RecommendRun(Base):
    __tablename__ = "recommend_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # map_id/requested_by: auth·maps가 아직 없어 String으로 받는다(pins.models와 같은 이유,
    # FK는 그 모듈들이 오면 건다 — 루트 보고 대상).
    map_id: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(Category, nullable=False)
    requested_by: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(RunStatus, nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # data-model.md엔 없는 컬럼 — GET /runs/{runId}/result(깔때기 표)가 매번 재계산하지
    # 않도록 마지막 execute/widen/retry 결과를 저장해둔다(candidates.lat/lng와 같은 종류의
    # 결정, for_Root.md에 보고). funnel은 파생값이라 정본은 항상 마지막 실행 결과다.
    last_funnel: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("recommend_runs.id"), nullable=False)
    # places(id) 대상 테이블은 있지만 아직 어떤 모듈도 실제로 채우지 않는다 — pins.place_id와
    # 같은 이유로 FK를 걸지 않는다(루트 보고 대상).
    place_id: Mapped[str] = mapped_column(String, nullable=False)
    region_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("regions.id"), nullable=True)
    # 위 모듈 docstring 참고 — data-model.md엔 없는 컬럼, pins.geom과 같은 이유로 denormalize.
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    checks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    member_fulfillment: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    published_pin_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EvidenceLine(Base):
    __tablename__ = "evidence_lines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("recommend_runs.id"), nullable=False)
    # auth가 아직 없어 String으로 받는다(pins.models와 같은 이유) — "자기가 쓴 것만 뺄 수
    # 있다"(5-5) 판정은 authz.core.can()이 author_id==user_id로 한다(evidence.disable).
    author_id: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(EvidenceSource, nullable=False)
    text: Mapped[str] = mapped_column(String, nullable=False)
    chip_id: Mapped[str | None] = mapped_column(String, nullable=True)
    badge: Mapped[str] = mapped_column(EvidenceBadge, nullable=False)
    fact_key: Mapped[str | None] = mapped_column(String, nullable=True)
    circle_anchor_pin_id: Mapped[str | None] = mapped_column(String, nullable=True)
    circle_radius_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Region(Base):
    __tablename__ = "regions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("recommend_runs.id"), nullable=False)
    signature: Mapped[str] = mapped_column(String, nullable=False)
    # 위 모듈 docstring — data-model.md의 geom geography 대신 병합된 원(중심+반경)을 그대로
    # 저장한다. places 없이는 label을 조회할 방법이 없어 label도 여기서 만들어 저장한다.
    label: Mapped[str] = mapped_column(String, nullable=False)
    center_lat: Mapped[float] = mapped_column(Float, nullable=False)
    center_lng: Mapped[float] = mapped_column(Float, nullable=False)
    radius_m: Mapped[int] = mapped_column(Integer, nullable=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Exclusion(Base):
    __tablename__ = "exclusions"
    __table_args__ = (UniqueConstraint("map_id", "requested_by", "place_id", name="uq_exclusions_map_requester_place"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    map_id: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(Category, nullable=False)
    place_id: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(ExclusionReason, nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("recommend_runs.id"), nullable=False)
    # #42 확정: 개인 단위 — requested_by가 unique 제약에 들어간다(map_id만으로는 부족).
    requested_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
