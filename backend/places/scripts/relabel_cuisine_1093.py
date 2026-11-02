"""기존 DB의 음식 종류(`cuisine_*`) 라벨 보정(#1093) — 적재 변환(`ingest.curated_labels_to_rows`)과 같은 규칙(`places.cuisine_names`)을 이미 적재된 place_facts에 적용한다.

    python -m places.scripts.relabel_cuisine_1093            # dry-run(기본): 아무것도 쓰지 않고 건수만 낸다
    python -m places.scripts.relabel_cuisine_1093 --apply    # 실제로 쓴다

규칙: 업종(license_business_type) 유래 cuisine_* 거짓 → 모름(unknown), 가게 이름 규칙에 걸린 키 → 참(menu_keyword),
이름이 외국 음식이면 업종 유래 한식 참 → 모름. 음식점 중 cuisine_* 라벨 행이 이미 있는 장소만 본다(적재 변환과 같은 범위 — 카페·관광지는 그대로, 새 라벨 행도 만들지 않는다).
**스테이징·운영 DB에는 루트가 사용자 승인을 받은 뒤에만 --apply 한다 — 한적한 시간에, dry-run으로 건수를 확인한 뒤.** 2000행씩 나눠 쓰지만 커밋 전까지 행 잠금이 이어진다(8610곳 로컬 실측 약 45초). 출력은 건수뿐이고 이름·접속 주소는 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import bindparam, func, select, update
from sqlalchemy.orm import Session

from common.database import SessionLocal
from places import cuisine_names, ingest
from places.models import Place, PlaceFact

BATCH = 2000


@dataclass(frozen=True)
class Change:
    place_id: object
    fact_key: str
    value: bool | None
    confidence: str
    evidence: str | None
    label_source: str | None
    kind: str   # "downgrade"(거짓→모름) | "name_true"(이름 규칙 참) | "korean_lowered"(한식 참→모름)


def _as_label(fact: PlaceFact) -> dict:
    value = "unknown" if fact.confidence == "unknown" else ("true" if fact.value else "false")
    return {"value": value, "evidence": fact.evidence or "", "source": fact.label_source or ""}


def plan_changes(db: Session) -> tuple[list[Change], int]:
    """(바꿀 라벨 목록, 훑은 음식점 수). 읽기만 한다."""
    rows = db.execute(
        select(PlaceFact, Place.name).join(Place, Place.id == PlaceFact.place_id)
        .where(Place.category == ingest.RESTAURANT_CATEGORY, PlaceFact.fact_key.like("cuisine\\_%", escape="\\"))   # 적재 변환(rest_ 접두어)과 같은 범위
        .order_by(PlaceFact.place_id)
    ).all()
    by_place: dict = {}
    for fact, name in rows:
        by_place.setdefault(fact.place_id, (name, {}))[1][fact.fact_key] = fact
    changes: list[Change] = []
    for place_id, (name, facts) in by_place.items():
        before = {k: _as_label(f) for k, f in facts.items()}
        after = cuisine_names.adjust_cuisine_labels(name, before)
        hits = cuisine_names.name_hits(name)
        for key, new in after.items():
            if key not in before or new == before[key]:
                continue   # 라벨 행이 없는 키는 만들지 않는다
            known = new["value"] != "unknown"
            if key in hits and new["value"] == "true":
                kind = "name_true"
            elif key == cuisine_names.KOREAN and before.get(key, {}).get("value") == "true":
                kind = "korean_lowered"
            else:
                kind = "downgrade"
            changes.append(Change(place_id, key, True if known else None, "known" if known else "unknown",
                                  new["evidence"] or None, new["source"] or None, kind))
    return changes, len(by_place)


def apply_changes(db: Session, changes: list[Change]) -> None:
    stmt = (
        update(PlaceFact)
        .where(PlaceFact.place_id == bindparam("b_place_id"), PlaceFact.fact_key == bindparam("b_fact_key"))
        .values(value=bindparam("b_value"), confidence=bindparam("b_confidence"), evidence=bindparam("b_evidence"),
                label_source=bindparam("b_label_source"), labeled_at=func.now())
    )
    for i in range(0, len(changes), BATCH):
        db.connection().execute(stmt, [{"b_place_id": c.place_id, "b_fact_key": c.fact_key, "b_value": c.value, "b_confidence": c.confidence,
                           "b_evidence": c.evidence, "b_label_source": c.label_source} for c in changes[i:i + BATCH]])


def summary(changes: list[Change], scanned: int) -> list[str]:
    by_kind = Counter(c.kind for c in changes)
    downgraded = Counter(c.fact_key for c in changes if c.kind == "downgrade")
    lines = [f"훑은 음식점(cuisine_* 라벨이 있는 곳): {scanned}", f"바꿀 라벨 전체: {len(changes)}"]
    lines += [f"  {kind}: {by_kind.get(kind, 0)}" for kind in ("downgrade", "name_true", "korean_lowered")]
    lines += [f"  거짓→모름 {key}: {n}" for key, n in sorted(downgraded.items())]
    return lines


def main(argv: list[str] | None = None, *, session_factory=SessionLocal) -> int:
    parser = argparse.ArgumentParser(description="cuisine_* 라벨 보정(#1093). 기본은 dry-run.")
    parser.add_argument("--apply", action="store_true", help="실제로 쓴다(기본은 건수만)")
    args = parser.parse_args(argv)
    db = session_factory()
    try:
        changes, scanned = plan_changes(db)
        for line in summary(changes, scanned):
            print(line)
        if not args.apply:
            print("dry-run — 아무것도 쓰지 않았다. 쓰려면 --apply")
            return 0
        apply_changes(db, changes)
        db.commit()
        print(f"적용했다: {len(changes)}개 라벨")
        return 0
    except Exception as exc:   # noqa: BLE001 — 타입만 남긴다
        db.rollback()
        print(f"실패({type(exc).__name__}) — 되돌렸다", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
