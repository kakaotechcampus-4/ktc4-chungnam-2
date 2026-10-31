"""
얇은 I/O 셸 — 이 모듈이 소유한 테이블(recommend_runs/candidates/evidence_lines/regions/
exclusions)만 건드린다(docs/code-quality.md). 다른 모듈 접근(pins.api/authz/llm.api(Gateway)/
recommend.ports 게이트웨이)은 이 파일에 두지 않는다 — flows.py가 한다(모듈 자체 관례,
flows.py 모듈 docstring 참고). event_log 기록만 예외다 — architecture.md 1.1절이 "모든
모듈이 record_event로 쓰는" event_log를 "다른 모듈의 테이블"로 세지 않는다고 명시한다.
"""

import uuid
from datetime import datetime, timezone
from typing import NamedTuple

from sqlalchemy import and_, delete, func, or_, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from common.errors import AppError
from recommend import core
from recommend.models import Candidate, EvidenceLine, Exclusion, IdempotencyKey, RecommendRun, Region


def create_run(db: Session, *, map_id: str, category: str, requested_by: str, attempt_no: int) -> RecommendRun:
    run = RecommendRun(
        map_id=map_id, category=category, requested_by=requested_by,
        status="collecting_evidence", attempt_no=attempt_no,
    )
    db.add(run)
    db.flush()
    return run


def list_runs_for_requester(
    db: Session, *, map_id: str, requested_by: str, category: str | None, limit: int,
) -> list[tuple[RecommendRun, int, int]]:
    """지난 추천 기록(#469) — (run, 후보 수, 게시 수). **requested_by가 본인인 run만**(가드레일 1). created_at 내림차순.
    후보·게시 수는 한 쿼리에서 집계한다(N+1 금지). 후보 수는 done이 아니면 0이다 — 진행 중·실패 run의 후보는 보여 주지 않는다."""
    counts = (
        select(
            Candidate.run_id.label("run_id"),
            func.count().label("candidate_count"),
            func.count(Candidate.published_pin_id).label("published_count"),
        )
        .group_by(Candidate.run_id)
        .subquery()
    )
    query = (
        select(RecommendRun, func.coalesce(counts.c.candidate_count, 0), func.coalesce(counts.c.published_count, 0))
        .outerjoin(counts, counts.c.run_id == RecommendRun.id)
        .where(RecommendRun.map_id == map_id, RecommendRun.requested_by == requested_by)
        .order_by(RecommendRun.created_at.desc(), RecommendRun.id.desc())
        .limit(limit)
    )
    if category is not None:
        query = query.where(RecommendRun.category == category)
    return [
        (run, candidate_count if run.status == "done" else 0, published_count)
        for run, candidate_count, published_count in db.execute(query).all()
    ]


def max_attempt_no_for_requester(db: Session, *, map_id: str, requested_by: str) -> int:
    """#31 확정: 개인 단위, 카테고리 무관 — 이 사람이 이 지도에서 만든 모든 run(카테고리
    무관)의 attempt_no 중 최댓값. run이 하나도 없으면 0."""
    result = db.execute(
        select(func.max(RecommendRun.attempt_no)).where(
            RecommendRun.map_id == map_id, RecommendRun.requested_by == requested_by,
        )
    ).scalar_one()
    return result or 0


# ---------- idempotency keys (#811) ----------

class Reservation(NamedTuple):
    outcome: str   # "owner"(이 요청이 모델을 부른다) | core.ReservationDecision 중 conflict·reuse·in_progress
    id: uuid.UUID
    generation: int
    run_id: uuid.UUID | None


def reserve_idempotency_key(
    db: Session, *, requested_by: str, key: str, request_hash: str, now: datetime,
) -> Reservation:
    """모델을 부르기 **전에** (요청자, 범위, 키)를 기록한다. 호출부가 독립 세션으로 부르고 바로 커밋한다 — 요청 세션에
    넣으면 모델 호출 전 rollback에 사라지거나, 둘째 INSERT가 첫째의 커밋(모델이 끝날 때)까지 기다린다. 커밋하지 않는다.
    새 행이면 owner. 이미 있으면 `core.reservation_decision`대로: 기한이 지난 미완료 예약은 FOR UPDATE로 잡고 세대를
    올려 owner가 된다(이어받기). 그 사이 owner가 행을 지워 읽을 게 없으면 한 번 더 시도한다."""
    for _ in range(3):
        inserted = db.execute(
            pg_insert(IdempotencyKey)
            .values(
                id=uuid.uuid4(), requested_by=requested_by, scope=core.IDEMPOTENCY_SCOPE, key=key,
                request_hash=request_hash, attempt=1, started_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_idempotency_keys")
            .returning(IdempotencyKey.id)
        ).scalar_one_or_none()
        if inserted is not None:
            return Reservation("owner", inserted, 1, None)
        existing = db.execute(
            select(IdempotencyKey)
            .where(
                IdempotencyKey.requested_by == requested_by, IdempotencyKey.scope == core.IDEMPOTENCY_SCOPE,
                IdempotencyKey.key == key,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if existing is None:
            continue
        decision = core.reservation_decision(
            stored_hash=existing.request_hash, request_hash=request_hash, run_id=existing.run_id,
            started_at=existing.started_at, now=now,
        )
        if decision == "takeover":
            existing.attempt += 1
            existing.started_at = now
            db.flush()
            return Reservation("owner", existing.id, existing.attempt, None)
        return Reservation(decision, existing.id, existing.attempt, existing.run_id)
    raise AppError("REQUEST_IN_PROGRESS")


def link_idempotency_key(db: Session, *, reservation_id: uuid.UUID, generation: int, run_id: uuid.UUID) -> None:
    """run을 만든 트랜잭션이 키 행에 run_id를 잇는다 — 자기 세대이고 아직 비어 있을 때만. rowcount가 0이면 처리 기한이
    지나 다른 요청이 이어받은 것이라(늦게 끝난 쪽) 저장을 거절한다: 예외로 이 트랜잭션이 통째로 되돌아간다."""
    result = db.execute(
        update(IdempotencyKey)
        .where(IdempotencyKey.id == reservation_id, IdempotencyKey.attempt == generation, IdempotencyKey.run_id.is_(None))
        .values(run_id=run_id)
    )
    if result.rowcount == 0:
        raise AppError("REQUEST_IN_PROGRESS")


def release_idempotency_key(db: Session, *, reservation_id: uuid.UUID, generation: int) -> None:
    """run을 못 만든 요청(모델 실패 등)이 자기 세대의 예약만 지워 같은 키의 재시도를 허용한다. 이어받은 쪽의 행이나 run이
    이미 이어진 행은 건드리지 않는다. 호출부가 독립 세션으로 부르고 커밋한다."""
    db.execute(
        delete(IdempotencyKey).where(
            IdempotencyKey.id == reservation_id, IdempotencyKey.attempt == generation, IdempotencyKey.run_id.is_(None),
        )
    )


def _expired_idempotency_keys(now: datetime):
    """24시간이 지난 키 행의 조건(#811). run이 연결된 행은 만든 지 24시간(created_at), 연결되지 않은 예약(run_id NULL)은
    현재 세대의 예약 시각(started_at — 이어받을 때 갱신된다)이 24시간 지난 것이다. 진행 중인 예약과 최근에 이어받은 예약은
    started_at이 최근이라 지워지지 않는다. 예약만 커밋하고 프로세스가 죽어 run이 영영 안 이어진 행이 남아 그 키가 24시간
    뒤에도 IDEMPOTENCY_CONFLICT를 내는 일을 막는다."""
    cutoff = now - core.IDEMPOTENCY_RETENTION
    return or_(
        and_(IdempotencyKey.run_id.is_not(None), IdempotencyKey.created_at < cutoff),
        and_(IdempotencyKey.run_id.is_(None), IdempotencyKey.started_at < cutoff),
    )


def purge_idempotency_keys(db: Session, *, now: datetime) -> int:
    """24시간이 지난 키 행을 지운다(maintenance). run이 연결된 행과 오래 방치된 미완료 예약을 지운다(조건은
    `_expired_idempotency_keys`)."""
    return db.execute(delete(IdempotencyKey).where(_expired_idempotency_keys(now))).rowcount


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
        select(Candidate).where(Candidate.id == candidate_uuid).execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if candidate is None:
        raise AppError("NOT_FOUND")
    run = db.execute(
        select(RecommendRun).where(RecommendRun.id == candidate.run_id).execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if run is None:
        raise AppError("NOT_FOUND")
    return candidate, run


def link_published_pin(db: Session, *, candidate_id: str, pin_id: str) -> None:
    """가드 UPDATE — WHERE published_pin_id IS NULL(mentor-review-plan.md "레이스 2번").
    rowcount==0이면 다른 경로로 이미 링크된 것 → 409 PIN_DUPLICATE(#255 — IDEMPOTENCY_CONFLICT는
    Idempotency-Key 충돌이라 뜻이 다르다), 호출부(flows.py)가
    커밋 전이라 이 예외로 인한 전체 롤백이 직전 pins INSERT까지 되돌린다."""
    result = db.execute(
        update(Candidate)
        .where(Candidate.id == uuid.UUID(candidate_id), Candidate.published_pin_id.is_(None))
        .values(published_pin_id=uuid.UUID(pin_id))
    )
    if result.rowcount == 0:
        raise AppError("PIN_DUPLICATE")


# ---------- evidence_lines ----------

def list_evidence(db: Session, run_id: str) -> list[EvidenceLine]:
    run_uuid = uuid.UUID(run_id)
    rows = db.execute(
        select(EvidenceLine).where(EvidenceLine.run_id == run_uuid).order_by(EvidenceLine.created_at, EvidenceLine.seq)
    ).scalars().all()
    return list(rows)


def list_active_evidence(db: Session, run_id: uuid.UUID) -> list[EvidenceLine]:
    rows = db.execute(
        select(EvidenceLine)
        .where(EvidenceLine.run_id == run_id, EvidenceLine.is_active.is_(True))
        .order_by(EvidenceLine.created_at, EvidenceLine.seq)
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
            chip_id=line.get("chip_id"), badge=line["badge"], fact_key=line.get("fact_key"), wants=line.get("wants"),
            circle_anchor_pin_id=line.get("circle_anchor_pin_id"), circle_radius_m=line.get("circle_radius_m"),
            is_active=line.get("is_active", True),
        ))
    db.flush()


def add_manual_evidence(
    db: Session, *, run_id: uuid.UUID, author_id: str, text: str, fact_key: str | None = None, wants: bool | None = None,
) -> EvidenceLine:
    """「+」로 직접 추가한 줄 — 배지는 preferred 고정(#707, ♥ 사유와 같은 규칙: 순위 점수에만 들어가고 후보를 거르지
    않는다). fact_key·wants는 ②(plan_evidence)가 붙인 값이다(#254) — 못 붙였으면 근거 줄에만 남고 효과가 없다."""
    line = EvidenceLine(
        run_id=run_id, author_id=author_id, source="manual", text=text,
        badge="preferred", fact_key=fact_key, wants=wants, is_active=True,
    )
    db.add(line)
    db.flush()
    return line


def list_manual_lines_by_author(db: Session, run_id: uuid.UUID, author_id: str) -> list[EvidenceLine]:
    """이 run에서 이 사람이 「+」로 추가한 줄 전부 — ×로 뺀 줄도 포함한다(같은 글 재추가의 멱등 판정, #848)."""
    return list(db.execute(
        select(EvidenceLine)
        .where(EvidenceLine.run_id == run_id, EvidenceLine.author_id == author_id, EvidenceLine.source == "manual")
        .order_by(EvidenceLine.created_at, EvidenceLine.seq)
        .execution_options(populate_existing=True)   # 잠근 뒤 다시 읽을 때 다른 요청이 바꾼 is_active를 본다
    ).scalars().all())


def count_manual_entries(db: Session, run_id: uuid.UUID) -> int:
    """이 run에 「+」로 추가한 글 수(#707) — ×로 뺀 줄도 센다. 글 하나에 조건이 여럿이면 줄이 여럿이라(#419)
    (text, created_at)으로 묶어 센다. created_at은 트랜잭션 시작 시각이라 한 요청에서 넣은 줄은 모두 같다 — 이 전제가
    깨지면(행마다 다른 시각) 줄 수로 세는 것과 같아져 더 엄격해진다. 한 요청 안의 같은 글은 flows가 미리 하나로 줄인다."""
    entries = (
        select(EvidenceLine.text, EvidenceLine.created_at)
        .where(EvidenceLine.run_id == run_id, EvidenceLine.source == "manual")
        .distinct()
        .subquery()
    )
    return db.execute(select(func.count()).select_from(entries)).scalar_one()


def lock_run(db: Session, run_id: uuid.UUID) -> None:
    """run 행을 FOR UPDATE로 잠근다 — 같은 run에 동시에 온 「+」 요청이 상한을 함께 넘지 못하게(#707, 멘토 리뷰 #380).
    실행·재시도·반경 넓히기·게시도 같은 잠금을 잡아 후보 교체와 겹치지 않게 한다(#811). 기다리는 사이 다른 요청이
    바꾼 값을 읽도록 이미 읽어 둔 run 객체도 새로 채운다. 잠금은 트랜잭션 끝(session_scope 커밋·롤백)에 풀린다.

    잠금 순서(교착 방지, #811): run → 요청자 횟수(`lock_requester_attempts`) → 후보 행. 거꾸로 잡지 않는다."""
    db.execute(
        select(RecommendRun).where(RecommendRun.id == run_id).with_for_update().execution_options(populate_existing=True)
    )


def lock_requester_attempts(db: Session, *, map_id: str, requested_by: str) -> None:
    """이 지도에서 이 사람의 추천 횟수(`attempt_no`)를 검사·소비하는 구간을 직렬화한다(#811). 횟수는 run 행이 아니라
    (지도, 요청자) 단위라 행 잠금으로는 못 막는다 — 트랜잭션 범위 advisory lock이다. 잠그고 나서 최댓값을 읽고, 상한을
    검사하고, INSERT·UPDATE까지 같은 트랜잭션에서 끝내야 두 요청이 같은 번호를 쓰지 않는다. 모델을 기다리는 동안에는
    잡지 않는다(모델 뒤 쓰기 구간만)."""
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"recommend_attempt:{map_id}:{requested_by}"},
    )


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


def set_run_outcome(db: Session, run: RecommendRun, *, applied_evidence: list[dict], new_count: int) -> None:
    """마지막 실행(execute·retry·widen)의 근거 스냅샷과 새로 찾은 후보 수를 저장한다(#845, #847). 다음 실행이 덮는다.
    new_count는 게시 후보를 뺀, 이번 실행이 새로 만든 후보 수라 그 뒤에 게시해도 바뀌지 않는다."""
    run.applied_evidence = applied_evidence
    run.last_new_count = new_count
    db.flush()


def bump_attempt_no(db: Session, run: RecommendRun) -> int:
    """#31은 개인 단위 공유 카운터다 — 이 run 자신의 attempt_no만 1 올리면(예전 버전) 그
    사람의 다른(더 최근) run이 이미 써둔 더 큰 값을 무시하고 낮은 값으로 되돌아갈 수 있다
    (아래 버그 설명 참고). 항상 "이 사람의 현재 최댓값 + 1"로 맞춘다(루트 수정, 2026-09-23 —
    Antigravity 검수로 발견: retry_run이 이 run 자신의 attempt_no만 보고 상한을 검사해서,
    오래된(attempt_no가 낮은) run을 골라 재시도하면 사실상 상한을 무제한 우회할 수 있었다)."""
    lock_requester_attempts(db, map_id=run.map_id, requested_by=run.requested_by)
    current_max = max_attempt_no_for_requester(db, map_id=run.map_id, requested_by=run.requested_by)
    run.attempt_no = current_max + 1
    db.flush()
    return run.attempt_no


# ---------- candidates ----------

def set_default_radius_walk_min(db: Session, run: RecommendRun, walk_min: int) -> None:
    run.default_radius_walk_min = walk_min
    db.flush()


_DROP_AUTHOR_FROM_SNAPSHOT = """
UPDATE recommend_runs SET applied_evidence = COALESCE((
    SELECT jsonb_agg(entry ORDER BY position) FROM jsonb_array_elements(applied_evidence) WITH ORDINALITY AS t(entry, position)
    WHERE entry->>'author_id' <> :user_id
), '[]'::jsonb)
WHERE applied_evidence IS NOT NULL
  AND EXISTS (SELECT 1 FROM jsonb_array_elements(applied_evidence) AS entry WHERE entry->>'author_id' = :user_id)
"""


def _drop_author_from_snapshots(db: Session, *, user_id: str, map_id: str | None = None) -> None:
    """근거 줄을 지울 때 실행 스냅샷(recommend_runs.applied_evidence, #847) 안의 그 사람 줄도 뺀다 — 스냅샷에 작성자 id와 사용자
    글이 들어 있어 그대로 두면 지운 글이 결과 응답에 남는다. map_id가 있으면 그 지도의 run만."""
    db.execute(text(_DROP_AUTHOR_FROM_SNAPSHOT + (" AND map_id = :map_id" if map_id else "")),
               {"user_id": user_id, **({"map_id": map_id} if map_id else {})})


def delete_evidence_lines_by_author(db: Session, *, user_id: str) -> int:
    """탈퇴 — 이 사용자가 쓴 근거 줄(모든 run)을 지우고 지운 개수를 돌려준다. 실행 스냅샷 안의 그 사람 줄도 뺀다(#847)."""
    result = db.execute(delete(EvidenceLine).where(EvidenceLine.author_id == user_id))
    _drop_author_from_snapshots(db, user_id=user_id)
    db.flush()
    return result.rowcount


def delete_evidence_lines_by_author_in_map(db: Session, *, user_id: str, map_id: str) -> int:
    """지도 나가기(#369) — 이 사용자가 그 지도의 run에 쓴 근거 줄만 지운다. 그 지도 run의 실행 스냅샷에서도 뺀다(#847)."""
    run_ids_on_map = select(RecommendRun.id).where(RecommendRun.map_id == map_id)
    result = db.execute(
        delete(EvidenceLine).where(EvidenceLine.author_id == user_id, EvidenceLine.run_id.in_(run_ids_on_map))
    )
    _drop_author_from_snapshots(db, user_id=user_id, map_id=map_id)
    db.flush()
    return result.rowcount


def replace_unpublished_candidates(db: Session, *, run_id: uuid.UUID, candidates_data: list[dict]) -> list[Candidate]:
    """실행/재시도/반경넓히기가 후보 집합을 다시 채울 때 쓴다. 이미 게시된(published_pin_id
    not null) 후보는 지우지 않는다 — 공개된 핀의 출처 기록이라 사라지면 안 된다."""
    db.execute(delete(Candidate).where(Candidate.run_id == run_id, Candidate.published_pin_id.is_(None)))
    # 남은 게시 후보의 순위 뒤에 이어 붙인다 — 새 후보가 1부터 다시 시작하면 순위가 겹친다.
    kept_max_rank = db.execute(select(func.max(Candidate.rank)).where(Candidate.run_id == run_id)).scalar() or 0
    rows = [Candidate(run_id=run_id, **{**data, "rank": data["rank"] + kept_max_rank}) for data in candidates_data]
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


def last_run_at_by_category(db: Session, *, map_id: str) -> dict[str, datetime]:
    """카테고리 → 그 카테고리 가장 최근 run의 created_at(#522). run이 없는 카테고리는 키가 없다."""
    rows = db.execute(
        select(RecommendRun.category, func.max(RecommendRun.created_at))
        .where(RecommendRun.map_id == map_id)
        .group_by(RecommendRun.category)
    ).all()
    return {category: created_at for category, created_at in rows}


def latest_run_place_ids(db: Session, *, map_id: str, requested_by: str, category: str | None = None) -> set[str]:
    """요청자의 이 지도 최신 run(카테고리마다 하나, category가 있으면 그것만)의 후보 place_id(#646)."""
    latest = (
        select(RecommendRun.id)
        .where(RecommendRun.map_id == map_id, RecommendRun.requested_by == requested_by)
        .distinct(RecommendRun.category)
        .order_by(RecommendRun.category, RecommendRun.created_at.desc(), RecommendRun.id.desc())
    )
    if category is not None:
        latest = latest.where(RecommendRun.category == category)
    return set(db.execute(select(Candidate.place_id).where(Candidate.run_id.in_(latest))).scalars())


def purge_map_data(db: Session, *, map_ids: list[str], now: datetime | None = None) -> dict[str, int]:
    """지도 정리(#431) — 이 지도들의 추천 기록을 지운다. 테이블 이름 → 지운 행 수. 자식(근거 줄·후보·지역·
    제외·멱등 키)부터 지우고 run을 마지막에 지운다(전부 recommend_runs를 참조, 후보는 지역도 참조해서 지역보다 먼저)."""
    names = ["evidence_lines", "candidates", "regions", "exclusions", "idempotency_keys", "recommend_runs"]
    if not map_ids:
        return dict.fromkeys(names, 0)
    run_ids = select(RecommendRun.id).where(RecommendRun.map_id.in_(map_ids))
    return {
        "evidence_lines": db.execute(delete(EvidenceLine).where(EvidenceLine.run_id.in_(run_ids))).rowcount,
        "candidates": db.execute(delete(Candidate).where(Candidate.run_id.in_(run_ids))).rowcount,
        "regions": db.execute(delete(Region).where(Region.run_id.in_(run_ids))).rowcount,
        "exclusions": db.execute(delete(Exclusion).where(Exclusion.map_id.in_(map_ids))).rowcount,
        # 키 행(#811): 이 지도 run에 연결된 것(FK가 cascade여도 여기서 명시한다)과, 지도 정보가 없는 미완료 예약(run_id NULL)
        # 중 24시간이 지난 것. 최근·진행 중인 예약은 maintenance의 기준(`_expired_idempotency_keys`)과 같아서 남는다.
        "idempotency_keys": db.execute(delete(IdempotencyKey).where(or_(
            IdempotencyKey.run_id.in_(run_ids), and_(IdempotencyKey.run_id.is_(None), _expired_idempotency_keys(now or datetime.now(timezone.utc))),
        ))).rowcount,
        "recommend_runs": db.execute(delete(RecommendRun).where(RecommendRun.map_id.in_(map_ids))).rowcount,
    }


def reassign_user(db: Session, *, from_user_id: str, to_user_id: str) -> dict[str, int]:
    """게스트 합치기(#560) — from_user의 run 요청자·근거 줄 작성자·제외 요청자를 to_user로 옮긴다. 테이블 이름 →
    옮긴(제외는 겹쳐서 지운 것 제외) 행 수. 같은 (지도, 장소) 제외가 to_user에게 이미 있으면 from_user 것을 지운다
    (uq_exclusions_map_requester_place, 카카오 계정 쪽이 이긴다). 멱등 키(#811)도 요청자를 옮기고, (범위, 키)가 겹치면
    from_user 것을 지운다(uq_idempotency_keys). attempt_no는 건드리지 않는다. 후보에는 요청자
    열이 없다(run의 requested_by를 따른다). 커밋하지 않는다."""
    if from_user_id == to_user_id:
        return {"recommend_runs": 0, "evidence_lines": 0, "exclusions": 0, "idempotency_keys": 0}
    db.execute(text("""
        UPDATE recommend_runs SET applied_evidence = (
            SELECT jsonb_agg(CASE WHEN entry->>'author_id' = :from_user THEN entry || jsonb_build_object('author_id', CAST(:to_user AS text))
                                  ELSE entry END ORDER BY position)
            FROM jsonb_array_elements(applied_evidence) WITH ORDINALITY AS t(entry, position))
        WHERE applied_evidence IS NOT NULL
          AND EXISTS (SELECT 1 FROM jsonb_array_elements(applied_evidence) AS entry WHERE entry->>'author_id' = :from_user)
    """), {"from_user": from_user_id, "to_user": to_user_id})   # 스냅샷의 작성자도 옮긴다(#847) — 근거 줄을 옮기는 것과 같다
    kept_keys = select(IdempotencyKey.scope, IdempotencyKey.key).where(IdempotencyKey.requested_by == to_user_id)
    db.execute(   # (범위, 키)가 겹치면 from_user 것을 지운다 — uq_idempotency_keys, 키는 24시간짜리라 잃어도 상관없다(#811)
        delete(IdempotencyKey).where(
            IdempotencyKey.requested_by == from_user_id, tuple_(IdempotencyKey.scope, IdempotencyKey.key).in_(kept_keys)
        )
    )
    kept = select(Exclusion.map_id, Exclusion.place_id).where(Exclusion.requested_by == to_user_id)
    db.execute(
        delete(Exclusion).where(
            Exclusion.requested_by == from_user_id, tuple_(Exclusion.map_id, Exclusion.place_id).in_(kept)
        )
    )
    return {
        "recommend_runs": db.execute(
            update(RecommendRun).where(RecommendRun.requested_by == from_user_id).values(requested_by=to_user_id)
        ).rowcount,
        "evidence_lines": db.execute(
            update(EvidenceLine).where(EvidenceLine.author_id == from_user_id).values(author_id=to_user_id)
        ).rowcount,
        "exclusions": db.execute(
            update(Exclusion).where(Exclusion.requested_by == from_user_id).values(requested_by=to_user_id)
        ).rowcount,
        "idempotency_keys": db.execute(
            update(IdempotencyKey).where(IdempotencyKey.requested_by == from_user_id).values(requested_by=to_user_id)
        ).rowcount,
    }
