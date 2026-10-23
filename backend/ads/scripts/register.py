"""광고 등록(docs/ads.md 8절, #648).

    python -m ads.scripts.register --csv <경로> [--dry-run]

CSV 첫 줄은 머리글 `place_id,starts_at,ends_at,memo`다(memo는 비워도 된다). 시각은 ISO 8601이고(예: 2026-11-01T00:00:00+09:00)
시간대가 없으면 AD_STATS_TZ(Asia/Seoul)로 본다. ends_at 시각은 포함하지 않는다.

행마다 검증한다 — place_id가 places에 있다, status가 open이다(추천 대상 카테고리), starts_at < ends_at, ends_at이 지금보다
뒤다, 그 장소에 active 광고가 이미 없다, CSV 안에서 같은 장소가 두 번 나오지 않는다. **하나라도 틀리면 아무것도 넣지 않는다.**
places는 places.api로만 읽는다(#113). places 행을 만들거나 고치지 않는다(명세 2절 1번).
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ads.core import STATS_TZ
from ads.models import Ad
from common import categories
from places import api as places_api

COLUMNS = ("place_id", "starts_at", "ends_at", "memo")
# status=open 확인용 반경. get_ad_places를 그 장소 자신의 좌표를 중심으로 불러 open과 카테고리만 본다.
_SELF_RADIUS_M = 1.0


@dataclass(frozen=True)
class AdDraft:
    line: int          # CSV 줄 번호(머리글이 1)
    place_id: str
    starts_at: datetime
    ends_at: datetime
    memo: str | None


class RegisterError(Exception):
    def __init__(self, errors: Sequence[str]):
        super().__init__("\n".join(errors))
        self.errors = list(errors)


def _parse_time(raw: str) -> datetime:
    value = datetime.fromisoformat(raw.strip())
    return value if value.tzinfo is not None else value.replace(tzinfo=STATS_TZ)


def parse_csv(text: str) -> tuple[list[AdDraft], list[str]]:
    """(읽은 행, 형식 오류). 형식이 틀린 행은 읽은 행에 들어가지 않는다."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if tuple(reader.fieldnames or ()) != COLUMNS:
        return [], [f"머리글이 {','.join(COLUMNS)}가 아니다: {','.join(reader.fieldnames or ())}"]
    drafts: list[AdDraft] = []
    errors: list[str] = []
    for line, row in enumerate(reader, start=2):
        try:
            place_id = str(uuid.UUID(row["place_id"].strip()))
        except (ValueError, AttributeError):
            errors.append(f"{line}줄: place_id 형식이 틀렸다({row['place_id']!r})")
            continue
        try:
            starts_at, ends_at = _parse_time(row["starts_at"] or ""), _parse_time(row["ends_at"] or "")
        except ValueError:
            errors.append(f"{line}줄: starts_at, ends_at은 ISO 8601 시각이어야 한다")
            continue
        memo = (row["memo"] or "").strip() or None
        drafts.append(AdDraft(line, place_id, starts_at, ends_at, memo))
    if not drafts and not errors:
        errors.append("등록할 행이 없다")
    return drafts, errors


def validate(db: Session, drafts: Sequence[AdDraft], *, now: datetime) -> list[str]:
    """명세 8절 검증. 오류 목록(비면 통과). 읽기만 한다."""
    errors: list[str] = []
    seen: dict[str, int] = {}
    for d in drafts:
        if d.place_id in seen:
            errors.append(f"{d.line}줄: 같은 장소가 {seen[d.place_id]}줄에 이미 있다({d.place_id})")
        seen.setdefault(d.place_id, d.line)
        if not d.starts_at < d.ends_at:
            errors.append(f"{d.line}줄: starts_at이 ends_at보다 앞이어야 한다")
        elif d.ends_at <= now:
            errors.append(f"{d.line}줄: ends_at이 이미 지났다")

    ids = list(seen)
    infos = places_api.get_places(ids, db=db)
    for d in drafts:
        info = infos.get(d.place_id)
        if info is None:
            errors.append(f"{d.line}줄: places에 없는 장소다({d.place_id})")
            continue
        open_here = places_api.get_ad_places(
            db, place_ids=[d.place_id], center=(info.lat, info.lng), radius_m=_SELF_RADIUS_M,
            categories=categories.recommendable(),
        )
        if not open_here:
            errors.append(f"{d.line}줄: status가 open이 아니거나 추천 대상 카테고리가 아니다({info.name})")

    taken = set(db.execute(select(Ad.place_id).where(Ad.place_id.in_(ids), Ad.active.is_(True))).scalars())
    errors.extend(f"{d.line}줄: 이 장소에 active 광고가 이미 있다({d.place_id})" for d in drafts if d.place_id in taken)
    return errors


def register(db: Session, drafts: Sequence[AdDraft], *, now: datetime) -> list[str]:
    """전부 통과하면 ads 행을 넣고 새 ad_id 목록을 돌려준다. 하나라도 틀리면 RegisterError이고 아무것도 넣지 않는다.
    커밋하지 않는다(main이 한다)."""
    errors = validate(db, drafts, now=now)
    if errors:
        raise RegisterError(errors)
    rows = [Ad(place_id=d.place_id, starts_at=d.starts_at, ends_at=d.ends_at, active=True, memo=d.memo) for d in drafts]
    db.add_all(rows)
    db.flush()
    return [str(r.id) for r in rows]


def main(argv: Sequence[str] | None = None) -> int:
    from common.database import SessionLocal

    parser = argparse.ArgumentParser(description="광고 등록 — 하나라도 틀리면 아무것도 넣지 않는다")
    parser.add_argument("--csv", required=True, type=Path, help="place_id,starts_at,ends_at,memo")
    parser.add_argument("--dry-run", action="store_true", help="검증만 하고 넣지 않는다")
    args = parser.parse_args(argv)

    drafts, errors = parse_csv(args.csv.read_text(encoding="utf-8"))
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    with SessionLocal() as db:
        try:
            ad_ids = register(db, drafts, now=datetime.now(timezone.utc))
        except RegisterError as exc:
            db.rollback()
            print("\n".join(exc.errors), file=sys.stderr)
            print("아무것도 넣지 않았다.", file=sys.stderr)
            return 1
        if args.dry_run:
            db.rollback()
            print(f"검증 통과 {len(drafts)}건(--dry-run, 넣지 않았다)")
            return 0
        db.commit()
    for d, ad_id in zip(drafts, ad_ids):
        print(f"{ad_id}\t{d.place_id}\t{d.starts_at.isoformat()} ~ {d.ends_at.isoformat()}")
    print(f"{len(ad_ids)}건 등록")
    return 0


if __name__ == "__main__":
    sys.exit(main())
