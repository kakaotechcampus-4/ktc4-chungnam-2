"""
얇은 I/O 셸 — 이 모듈이 소유한 테이블(recommend_runs/candidates/evidence_lines/regions/
exclusions)만 건드린다(docs/code-quality.md). 다른 모듈 접근(pins.api/authz/llm.service/
recommend.ports 게이트웨이)은 이 파일에 두지 않는다 — flows.py가 한다(모듈 자체 관례,
flows.py 모듈 docstring 참고). event_log 기록만 예외다 — architecture.md 1.1절이 "모든
모듈이 record_event로 쓰는" event_log를 "다른 모듈의 테이블"로 세지 않는다고 명시한다.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from common.errors import AppError
from recommend.models import Candidate, EvidenceLine, Exclusion, RecommendRun, Region


def create_run(db: Session, *, map_id: str, category: str, requested_by: str, attempt_no: int) -> RecommendRun:
    run = RecommendRun(
        map_id=map_id, category=category, requested_by=requested_by,
        status="collecting_evidence", attempt_no=attempt_no,
    )
    db.add(run)
    db.flush()
    return run


def max_attempt_no_for_requester(db: Session, *, map_id: str, requested_by: str) -> int:
    """#31 확정: 개인 단위, 카테고리 무관 — 이 사람이 이 지도에서 만든 모든 run(카테고리
    무관)의 attempt_no 중 최댓값. run이 하나도 없으면 0."""
    result = db.execute(
        select(func.max(RecommendRun.attempt_no)).where(
            RecommendRun.map_id == map_id, RecommendRun.requested_by == requested_by,
        )
    ).scalar_one()
    return result or 0


def get_run_or_404(db: Session, run_id: str) -> RecommendRun:
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise AppError("NOT_FOUND") from None
    run = db.execute(select(RecommendRun).where(RecommendRun.id == run_uuid)).scalar_one_or_none()
    if run is None:
        raise AppError("NOT_FOUND")
    return run


def load_candidate_with_run(db: Session, candidate_id: str) -> tuple[Candidate, RecommendRun]:
    """candidate와 그 run을 함께 읽는다. candidate가 없거나(형식 오류 포함) run 자체가
    없으면(정합성 버그 — 있어선 안 되지만 사용자에게 다른 코드를 보여줄 이유가 없다)
    404 NOT_FOUND(pins.service.get_pin_or_404와 같은 패턴)."""
    try:
        candidate_uuid = uuid.UUID(candidate_id)
    except ValueError:
        raise AppError("NOT_FOUND") from None
    candidate = db.execute(
        select(Candidate).where(Candidate.id == candidate_uuid)
    ).scalar_one_or_none()
    if candidate is None:
        raise AppError("NOT_FOUND")
    run = db.execute(
        select(RecommendRun).where(RecommendRun.id == candidate.run_id)
    ).scalar_one_or_none()
    if run is None:
        raise AppError("NOT_FOUND")
    return candidate, run


def link_published_pin(db: Session, *, candidate_id: str, pin_id: str) -> None:
    """가드 UPDATE — WHERE published_pin_id IS NULL(mentor-review-plan.md "레이스 2번").
    rowcount==0이면 다른 경로로 이미 링크된 것 → 409 IDEMPOTENCY_CONFLICT, 호출부(flows.py)가
    커밋 전이라 이 예외로 인한 전체 롤백이 직전 pins INSERT까지 되돌린다."""
    result = db.execute(
        update(Candidate)
        .where(Candidate.id == uuid.UUID(candidate_id), Candidate.published_pin_id.is_(None))
        .values(published_pin_id=uuid.UUID(pin_id))
    )
    if result.rowcount == 0:
        raise AppError("IDEMPOTENCY_CONFLICT")


# ---------- evidence_lines ----------

def list_evidence(db: Session, run_id: str) -> list[EvidenceLine]:
    run_uuid = uuid.UUID(run_id)
    rows = db.execute(
        select(EvidenceLine).where(EvidenceLine.run_id == run_uuid).order_by(EvidenceLine.created_at)
    ).scalars().all()
    return list(rows)


def list_active_evidence(db: Session, run_id: uuid.UUID) -> list[EvidenceLine]:
    rows = db.execute(
        select(EvidenceLine).where(EvidenceLine.run_id == run_id, EvidenceLine.is_active.is_(True))
    ).scalars().all()
    return list(rows)


def add_reaction_evidence(db: Session, *, run_id: uuid.UUID, lines: list[dict]) -> None:
    """run 생성 시(①②) 반응에서 파생된 근거를 일괄 삽입한다. lines의 각 dict는
    llm.schemas.EvidenceLine.model_dump() 모양(author_id/source/text/badge/fact_key/
    circle_anchor_pin_id/circle_radius_m/is_active 등)이라고 전제한다 — id/run_id/created_at
    같은 DB가 직접 채우는 필드는 명시적으로 골라 쓰고 나머지는 무시한다(그대로 **line으로
    풀면 id=None이 PK 기본값(uuid.uuid4)을 덮어써 버린다)."""
    for line in lines:
        db.add(EvidenceLine(
            run_id=run_id, author_id=line["author_id"], source=line["source"], text=line["text"],
            chip_id=line.get("chip_id"), badge=line["badge"], fact_key=line.get("fact_key"),
            circle_anchor_pin_id=line.get("circle_anchor_pin_id"), circle_radius_m=line.get("circle_radius_m"),
            is_active=line.get("is_active", True),
        ))
    db.flush()


def add_manual_evidence(db: Session, *, run_id: uuid.UUID, author_id: str, text: str) -> EvidenceLine:
    line = EvidenceLine(
        run_id=run_id, author_id=author_id, source="manual", text=text,
        badge="reference", fact_key=None, is_active=True,
    )
    db.add(line)
    db.flush()
    return line


def get_evidence_or_none(db: Session, evidence_id: str) -> EvidenceLine | None:
    try:
        evidence_uuid = uuid.UUID(evidence_id)
    except ValueError:
        return None
    return db.execute(select(EvidenceLine).where(EvidenceLine.id == evidence_uuid)).scalar_one_or_none()


def set_evidence_active(db: Session, evidence_id: uuid.UUID, is_active: bool) -> None:
    db.execute(update(EvidenceLine).where(EvidenceLine.id == evidence_id).values(is_active=is_active))


# ---------- regions ----------

def list_regions(db: Session, run_id: str) -> list[Region]:
    run_uuid = uuid.UUID(run_id)
    return list(db.execute(select(Region).where(Region.run_id == run_uuid).order_by(Region.label)).scalars().all())


def create_regions(db: Session, *, run_id: uuid.UUID, regions_data: list[dict]) -> list[Region]:
    """run 생성 시 최초 1회만 쓴다 — 이 시점엔 아직 candidates.region_id가 이 지역을 참조할
    수 없으므로(후보가 없다) 안전하게 새로 만든다. 이후 반경을 바꿀 때는 이 함수가 아니라
    update_region_radius로 같은 행을 갱신한다(이미 게시된 candidates.region_id FK가 살아있는
    행을 가리키고 있어 지웠다 다시 만들면 안 된다)."""
    rows = [Region(run_id=run_id, **data) for data in regions_data]
    db.add_all(rows)
    db.flush()
    return rows


def update_region_radius(db: Session, region: Region, *, radius_m: int, signature: str) -> None:
    """반경 넓히기(5-6-1, 가드레일4) — 같은 지역 행을 그대로 갱신한다(id 불변, 이미 게시된
    candidates.region_id FK를 깨지 않는다)."""
    region.radius_m = radius_m
    region.signature = signature
    db.flush()


def confirm_all_regions(db: Session, run_id: uuid.UUID) -> None:
    db.execute(
        update(Region).where(Region.run_id == run_id).values(confirmed=True, confirmed_at=datetime.now(timezone.utc))
    )


def set_run_status(db: Session, run: RecommendRun, status: str) -> None:
    run.status = status
    db.flush()


def set_last_funnel(db: Session, run: RecommendRun, funnel: list[dict]) -> None:
    run.last_funnel = funnel
    db.flush()


def bump_attempt_no(db: Session, run: RecommendRun) -> int:
    """#31은 개인 단위 공유 카운터다 — 이 run 자신의 attempt_no만 1 올리면(예전 버전) 그
    사람의 다른(더 최근) run이 이미 써둔 더 큰 값을 무시하고 낮은 값으로 되돌아갈 수 있다
    (아래 버그 설명 참고). 항상 "이 사람의 현재 최댓값 + 1"로 맞춘다(루트 수정, 2026-09-23 —
    Antigravity 검수로 발견: retry_run이 이 run 자신의 attempt_no만 보고 상한을 검사해서,
    오래된(attempt_no가 낮은) run을 골라 재시도하면 사실상 상한을 무제한 우회할 수 있었다)."""
    current_max = max_attempt_no_for_requester(db, map_id=run.map_id, requested_by=run.requested_by)
    run.attempt_no = current_max + 1
    db.flush()
    return run.attempt_no


# ---------- candidates ----------

def replace_unpublished_candidates(db: Session, *, run_id: uuid.UUID, candidates_data: list[dict]) -> list[Candidate]:
    """실행/재시도/반경넓히기가 후보 집합을 다시 채울 때 쓴다. 이미 게시된(published_pin_id
    not null) 후보는 지우지 않는다 — 공개된 핀의 출처 기록이라 사라지면 안 된다."""
    db.execute(delete(Candidate).where(Candidate.run_id == run_id, Candidate.published_pin_id.is_(None)))
    rows = [Candidate(run_id=run_id, **data) for data in candidates_data]
    db.add_all(rows)
    db.flush()
    return rows


def list_candidates(db: Session, run_id: str) -> list[Candidate]:
    run_uuid = uuid.UUID(run_id)
    return list(
        db.execute(select(Candidate).where(Candidate.run_id == run_uuid).order_by(Candidate.rank)).scalars().all()
    )


# ---------- exclusions ----------

def add_exclusions(db: Session, *, map_id: str, category: str, place_ids: list[str], reason: str,
                    run_id: uuid.UUID, requested_by: str) -> None:
    """#42 확정: 개인 단위 unique(map_id, requested_by, place_id) — 이미 있는 조합은 조용히
    건너뛴다(같은 곳을 같은 사람이 여러 run에서 반복 제외해도 에러가 아니다)."""
    if not place_ids:
        return
    for place_id in place_ids:
        stmt = pg_insert(Exclusion).values(
            map_id=map_id, category=category, place_id=place_id, reason=reason,
            run_id=run_id, requested_by=requested_by,
        ).on_conflict_do_nothing(constraint="uq_exclusions_map_requester_place")
        db.execute(stmt)


def list_excluded_place_ids(db: Session, *, map_id: str, requested_by: str) -> set[str]:
    rows = db.execute(
        select(Exclusion.place_id).where(Exclusion.map_id == map_id, Exclusion.requested_by == requested_by)
    ).scalars().all()
    return set(rows)
