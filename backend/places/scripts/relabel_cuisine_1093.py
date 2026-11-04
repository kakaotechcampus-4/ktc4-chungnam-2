"""기존 DB의 음식 종류(`cuisine_*`) 라벨 보정(#1093) — 적재 변환(`ingest.curated_labels_to_rows`)과 같은 규칙(`places.cuisine_names`)을 이미 적재된 place_facts에 적용한다.

    python -m places.scripts.relabel_cuisine_1093                                   # dry-run(기본): 아무것도 쓰지 않고 건수만 낸다
    python -m places.scripts.relabel_cuisine_1093 --plan-out before.jsonl           # dry-run + 적용 전 값 파일 내보내기
    python -m places.scripts.relabel_cuisine_1093 --plan-out before.jsonl --apply   # 내보내고 실제로 쓴다

규칙: 업종(license_business_type) 유래 cuisine_* 거짓 → 모름(unknown), 가게 이름 규칙에 걸린 키 → 참(menu_keyword),
이름이 외국 음식이면 업종 유래 한식 참 → 모름. 음식점 중 cuisine_* 라벨 행이 이미 있는 장소만 본다(적재 변환과 같은 범위 — 카페·관광지는 그대로, 새 라벨 행도 만들지 않는다).
**스테이징·운영 DB에는 루트가 사용자 승인을 받은 뒤에만 --apply 한다 — 한적한 시간에, dry-run으로 건수를 확인한 뒤.**

보강(#1202):
- `--plan-out`: 바뀔 행의 적용 전 place_facts 전체 컬럼을 UTF-8 JSON Lines로 남긴다(복구용 before-image). 이미 있는 파일은 덮어쓰지 않고 실패한다. 이름·접속 주소 같은 비밀은 없지만 장소 id가 있으니 접근을 제한해 보관한다.
- `--apply`는 advisory lock을 잡아 동시 실행을 막는다. UPDATE는 적용 전 값이 그대로일 때만 바꾼다(CAS) — 그사이 새로 쓴 라벨은 덮지 않는다.
- 적용 건수가 계획 건수와 다르면 commit하지 않고 되돌린다.
- 계획은 장소 단위로 흘려 읽고(yield_per) 임시 JSONL 파일에 쌓아 메모리에 전체를 올리지 않는다. 진행률은 건수·초만 출력한다.
- 쓰기는 BATCH(2000)건씩 묶어 실행하지만 commit은 마지막 한 번이다 — 커밋 전까지 행 잠금이 이어진다. chunk commit으로 바꿀지는 스테이징 측정 뒤 정한다.
출력은 건수와 시간뿐이고 이름·접속 주소는 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime
from uuid import UUID

from sqlalchemy import bindparam, func, select, update
from sqlalchemy.orm import Session

from common.database import SessionLocal
from places import cuisine_names, ingest
from places.models import Place, PlaceFact

BATCH = 2000
LOCK_ID = 10931202   # 동시 실행 차단용 advisory lock 키(#1093 + #1202)
FACT_COLUMNS = tuple(column.name for column in PlaceFact.__table__.columns)
_COLUMN_TYPES = {column.name: column.type for column in PlaceFact.__table__.columns}


def _as_label(fact: PlaceFact) -> dict:
    value = "unknown" if fact.confidence == "unknown" else ("true" if fact.value else "false")
    return {"value": value, "evidence": fact.evidence or "", "source": fact.label_source or ""}


def _json_default(value):
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def _restore_before(row: dict) -> dict:
    """JSONL에서 읽은 적용 전 값을 DB 타입으로 되돌린다."""
    row = dict(row)
    row["place_id"] = UUID(row["place_id"])
    row["labeled_at"] = datetime.fromisoformat(row["labeled_at"])
    return row


def plan_changes(db: Session, spool, plan_out, started: float):
    """장소 하나씩 흘려 읽는다. 전체 계획은 spool(JSONL 임시 파일)에 쌓고 메모리에 두지 않는다.

    반환: (훑은 음식점 수, 바꿀 라벨 수, 종류별 건수, 키별 거짓→모름 건수). 읽기만 한다.
    """
    query = (
        select(PlaceFact, Place.name).join(Place, Place.id == PlaceFact.place_id)
        .where(Place.category == ingest.RESTAURANT_CATEGORY, PlaceFact.fact_key.like("cuisine\\_%", escape="\\"))   # 적재 변환(rest_ 접두어)과 같은 범위
        .order_by(PlaceFact.place_id, PlaceFact.fact_key)
        .execution_options(yield_per=BATCH)
    )
    scanned = total = 0
    by_kind: Counter = Counter()
    downgraded: Counter = Counter()
    for _, rows in itertools.groupby(db.execute(query), key=lambda row: row[0].place_id):
        group = list(rows)
        name = group[0][1]
        facts = {fact.fact_key: fact for fact, _ in group}
        before = {k: _as_label(f) for k, f in facts.items()}
        after = cuisine_names.adjust_cuisine_labels(name, before)
        hits = cuisine_names.name_hits(name)
        for key, new in after.items():
            if key not in before or new == before[key]:
                continue   # 라벨 행이 없는 키는 만들지 않는다
            known = new["value"] != "unknown"
            if key in hits and new["value"] == "true":
                kind = "name_true"
            elif key == cuisine_names.KOREAN and before[key]["value"] == "true":
                kind = "korean_lowered"
            else:
                kind = "downgrade"
            original = {column: getattr(facts[key], column) for column in FACT_COLUMNS}
            record = {"before": original, "value": True if known else None, "confidence": "known" if known else "unknown",
                      "evidence": new["evidence"] or None, "label_source": new["source"] or None, "kind": kind}
            spool.write(json.dumps(record, ensure_ascii=False, default=_json_default) + "\n")
            if plan_out is not None:
                plan_out.write(json.dumps(original, ensure_ascii=False, default=_json_default) + "\n")
            total += 1
            by_kind[kind] += 1
            if kind == "downgrade":
                downgraded[key] += 1
        scanned += 1
        if scanned % BATCH == 0:
            print(f"계획 진행: 음식점 {scanned}곳, 변경 {total}건, {time.monotonic() - started:.1f}초", flush=True)
    return scanned, total, by_kind, downgraded


def _read_batches(spool):
    spool.seek(0)
    while True:
        lines = list(itertools.islice(spool, BATCH))
        if not lines:
            return
        yield [json.loads(line) for line in lines]


def apply_changes(db: Session, spool, total: int, started: float) -> int:
    """BATCH건씩 묶어 UPDATE한다. 적용 전 값이 그대로인 행만 바뀐다(CAS). 실제로 바뀐 행 수를 돌려준다."""
    cas = [getattr(PlaceFact, column).is_not_distinct_from(bindparam(f"o_{column}", type_=_COLUMN_TYPES[column]))
           for column in FACT_COLUMNS]
    stmt = update(PlaceFact).where(*cas).values(
        value=bindparam("n_value", type_=_COLUMN_TYPES["value"]), confidence=bindparam("n_confidence"),
        evidence=bindparam("n_evidence"), label_source=bindparam("n_label_source"), labeled_at=func.now(),
    ).execution_options(synchronize_session=False)
    applied = done = 0
    for batch in _read_batches(spool):
        params = []
        for record in batch:
            before = _restore_before(record["before"])
            params.append({**{f"o_{column}": before[column] for column in FACT_COLUMNS},
                           "n_value": record["value"], "n_confidence": record["confidence"],
                           "n_evidence": record["evidence"], "n_label_source": record["label_source"]})
        applied += db.connection().execute(stmt, params).rowcount
        done += len(batch)
        print(f"적용 진행: {done}/{total}건, 성공 {applied}건, {time.monotonic() - started:.1f}초", flush=True)
    return applied


def main(argv: list[str] | None = None, *, session_factory=SessionLocal) -> int:
    parser = argparse.ArgumentParser(description="cuisine_* 라벨 보정(#1093). 기본은 dry-run.")
    parser.add_argument("--apply", action="store_true", help="실제로 쓴다(기본은 건수만)")
    parser.add_argument("--plan-out", help="바뀔 행의 적용 전 place_facts 전체 컬럼을 JSON Lines로 내보낼 파일(이미 있으면 실패, 덮어쓰지 않음)")
    args = parser.parse_args(argv)
    started = time.monotonic()
    db = session_factory()
    try:
        if args.apply and not db.scalar(select(func.pg_try_advisory_xact_lock(LOCK_ID))):   # 트랜잭션이 끝나면 풀린다
            print("실패 — 다른 라벨 갱신이 실행 중이다", file=sys.stderr)
            db.rollback()
            return 1
        with tempfile.TemporaryFile("w+", encoding="utf-8", newline="\n") as spool:
            if args.plan_out:
                with open(args.plan_out, "x", encoding="utf-8", newline="\n") as output:   # "x": 기존 파일을 덮어쓰지 않는다
                    scanned, total, by_kind, downgraded = plan_changes(db, spool, output, started)
            else:
                scanned, total, by_kind, downgraded = plan_changes(db, spool, None, started)
            print(f"훑은 음식점(cuisine_* 라벨이 있는 곳): {scanned}")
            print(f"바꿀 라벨 전체: {total}")
            for kind in ("downgrade", "name_true", "korean_lowered"):
                print(f"  {kind}: {by_kind[kind]}")
            for key, count in sorted(downgraded.items()):
                print(f"  거짓→모름 {key}: {count}")
            if not args.apply:
                print(f"dry-run — 아무것도 쓰지 않았다. 쓰려면 --apply ({time.monotonic() - started:.1f}초)")
                return 0
            applied = apply_changes(db, spool, total, started)
            if applied != total:
                print(f"실패 — 계획 {total}건과 적용 {applied}건이 다르다. 되돌렸다", file=sys.stderr)
                db.rollback()
                return 1
            db.commit()
            print(f"적용했다: {applied}개 라벨 ({time.monotonic() - started:.1f}초)")
            return 0
    except Exception as exc:   # noqa: BLE001 — 예외 내용은 출력하지 않고 타입만 남긴다
        db.rollback()
        print(f"실패({type(exc).__name__}) — 되돌렸다", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
