"""places.can_recommend 전체 재계산 — 규칙은 places/core.py(임계는 거기 상수).

    python -m places.scripts.recompute_can_recommend [--dry-run]

라벨이 늘거나 적재가 끝난 뒤, 임계를 바꾼 뒤에 돌린다. 멱등이다. 분류별 true/false 건수를 보고한다.
places.load는 적재 끝에 같은 함수를 자동으로 부른다. 새 모델 호출·카카오 호출은 없다.
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable

from sqlalchemy.orm import Session

from places import repository


def report_lines(result: repository.RecomputeResult, *, dry_run: bool) -> list[str]:
    lines = ["[can_recommend] 분류별 true / false"]
    for category in sorted({c for c, _ in result.counts}):
        t, f = result.counts.get((category, True), 0), result.counts.get((category, False), 0)
        lines.append(f"  {category}: {t} / {f}")
    total_t = sum(n for (_, v), n in result.counts.items() if v)
    total_f = sum(n for (_, v), n in result.counts.items() if not v)
    lines.append(f"  합계: {total_t} / {total_f}")
    lines.append(f"값이 {'바뀔' if dry_run else '바뀐'} 장소 {result.changed}곳")
    return lines


def main(argv: list[str] | None = None, *, session_factory: Callable[[], Session] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m places.scripts.recompute_can_recommend", description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="계산만 하고 DB는 바꾸지 않는다(롤백)")
    args = parser.parse_args(argv)
    if session_factory is None:
        from common.database import SessionLocal

        session_factory = SessionLocal
    db = session_factory()
    try:
        result = repository.recompute_can_recommend(db, dry_run=args.dry_run)
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    lines = report_lines(result, dry_run=args.dry_run)
    if args.dry_run:
        lines.append("(dry-run — DB에 쓰지 않았다)")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
