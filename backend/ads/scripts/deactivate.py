"""광고 내리기(docs/ads.md 8절, #648) — 기간과 별개로 즉시 노출을 멈춘다. 집계 행은 그대로 둔다.

    python -m ads.scripts.deactivate <ad_id>

이미 내린 광고면 그대로 두고 알린다. 없는 ad_id는 종료 코드 1.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from collections.abc import Sequence

from sqlalchemy.orm import Session

from ads.models import Ad


def deactivate(db: Session, ad_id: str) -> bool | None:
    """active를 false로. 바꿨으면 True, 이미 false였으면 False, 없으면 None. 커밋하지 않는다."""
    try:
        row = db.get(Ad, uuid.UUID(ad_id))
    except ValueError:
        return None
    if row is None:
        return None
    if not row.active:
        return False
    row.active = False
    db.flush()
    return True


def main(argv: Sequence[str] | None = None) -> int:
    from common.database import SessionLocal

    parser = argparse.ArgumentParser(description="광고 내리기(active=false)")
    parser.add_argument("ad_id")
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        changed = deactivate(db, args.ad_id)
        db.commit()
    if changed is None:
        print(f"없는 광고다: {args.ad_id}", file=sys.stderr)
        return 1
    print("내렸다" if changed else "이미 내린 광고다", args.ad_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
