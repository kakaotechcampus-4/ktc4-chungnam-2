"""
이 모듈이 소유하는 테이블 중 flows.py::publish_candidate에 필요한 최소 스켈레톤만 정의한다
(docs/data-model.md 117-159행, mentor-review-plan.md "착수 가능해지는 조건" 2번).
evidence_lines/regions/exclusions은 근거 조립·지역확인·재시도(이 세션의 후속 범위) 작업에서
추가한다 — 지금 만들면 그 세션들이 실제로 쓰지 않는 스켈레톤을 미리 얼려두는 꼴이라 만들지
않는다.

**data-model.md 대비 실제 구현 차이 (for_Root.md에 정리)**: `candidates`에 `lat`/`lng`를
추가했다. data-model.md의 candidates 정의(144-150행)엔 없는 컬럼이지만, publish_candidate가
`pins.api.create_ai_pin(lat=..., lng=...)`를 부르려면 좌표가 있어야 하고 `places` 모듈이
아직 없어(온디맨드 조회 불가) 후보 생성 시점에 좌표를 직접 들고 있는 수밖에 없다 —
`pins.geom`이 `places.geom`을 참조하지 않고 자기 것을 따로 갖는 것과 같은 이유(차원 압축·
architecture.md 3층 모델과 같은 결의 결정). region_id도 마찬가지로 `regions` 테이블이 아직
없어 FK 없이 컬럼만 둔다.

category/status는 pins.models의 동명 개념과 값이 같지만, 별도 Postgres ENUM 타입 이름
(recommend_category/recommend_run_status)을 쓴다 — recommend/CLAUDE.md "pins.models를
직접 import하지 않는다"를 지키면서 같은 이름의 enum 타입을 같은 metadata에 두 번 만들려는
충돌도 피한다.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from common.database import Base

Category = Enum("음식점", "카페", "숙소", "관광지", name="recommend_category")
RunStatus = Enum(
    "collecting_evidence", "awaiting_region_confirm", "executing", "done", "failed",
    name="recommend_run_status",
)


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("recommend_runs.id"), nullable=False)
    # places(id) 대상 테이블은 있지만 아직 어떤 모듈도 실제로 채우지 않는다 — pins.place_id와
    # 같은 이유로 FK를 걸지 않는다(루트 보고 대상).
    place_id: Mapped[str] = mapped_column(String, nullable=False)
    # regions 테이블은 이 세션 범위 밖(지역확인 세션이 추가) — FK 없이 컬럼만 둔다.
    region_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # 위 모듈 docstring 참고 — data-model.md엔 없는 컬럼, pins.geom과 같은 이유로 denormalize.
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    checks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    member_fulfillment: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    published_pin_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
