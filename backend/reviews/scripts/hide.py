"""후기 숨기기·되돌리기(docs/credits-reviews.md 5절 「숨김」, #432 D8) — 숨김을 바꾸는 길은 이 스크립트 하나다.

    python -m reviews.scripts.hide <review_id>          # 숨기기
    python -m reviews.scripts.hide <review_id> --undo   # 되돌리기

숨긴 후기는 목록·평균·개수·mine에서 빠지고 신고할 수 없다. 작성자 본인에게도 안 보인다. 신고 행은 그대로 둔다.
이미 그 상태면 그대로 두고 알린다. 없는 review_id는 종료 코드 1.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from collections.abc import Sequence

from sqlalchemy import func
from sqlalchemy.orm import Session

from reviews.models import Review


def set_hidden(db: Session, review_id: str, *, hidden: bool) -> bool | None:
    """숨김을 바꾼다. 바꿨으면 True, 이미 그 상태였으면 False, 없으면 None. 커밋하지 않는다."""
    try:
        row = db.get(Review, uuid.UUID(review_id))
    except ValueError:
        return None
    if row is None:
        return None
    if (row.hidden_at is not None) == hidden:
        return False
    row.hidden_at = func.now() if hidden else None
    db.flush()
    return True


def main(argv: Sequence[str] | None = None) -> int:
    from common.database import SessionLocal

    parser = argparse.ArgumentParser(description="후기 숨기기(--undo면 되돌리기)")
    parser.add_argument("review_id")
    parser.add_argument("--undo", action="store_true", help="숨김을 푼다")
    args = parser.parse_args(argv)

    hidden = not args.undo
    with SessionLocal() as db:
        changed = set_hidden(db, args.review_id, hidden=hidden)
        db.commit()
    if changed is None:
        print(f"없는 후기다: {args.review_id}", file=sys.stderr)
        return 1
    if changed:
        print("숨겼다" if hidden else "되돌렸다", args.review_id)
    else:
        print("이미 숨긴 후기다" if hidden else "숨기지 않은 후기다", args.review_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
