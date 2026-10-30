"""정기 정리 러너(#168). 사용법:

    python -m maintenance.run [--dry-run] [--only maps|notifications|guests|llm_calls]

한 번 돌리면 ① 삭제한 지 30일 지난 지도 ② 90일 지난 알림 ③ 90일 안 쓴 게스트 ④ 30일 지난 모델 호출 사용량(#870)을 차례로 지운다.
실제 삭제는 각 모듈이 한다(`maps.api.purge_deleted_maps`, `notifications.api.purge_old`, `auth.api.purge_inactive_guests`,
`llm.api.purge_old`) — 여기는 부르기만 한다.

- 단계마다 별도 세션·트랜잭션·커밋이다. 한 단계가 실패하면 그 단계만 되돌리고 다음으로 넘어간다. 실패는 로그에 단계
  이름과 에러 타입만 남긴다(메시지에는 사용자 데이터가 섞일 수 있다). 하나라도 실패하면 종료 코드는 1이다.
- `--dry-run`은 같은 삭제를 실행한 뒤 롤백해 지울 행 수만 보여 준다.
- agent의 일일 정리(`agent.flows.daily_cleanup_if_due`)는 프로세스 안에서 도는 것이라 여기 넣지 않는다.
"""

import argparse
import logging
import sys
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy.orm import Session

logger = logging.getLogger("maintenance")

MAP_RETENTION_DAYS = 30
GUEST_INACTIVE_DAYS = 90

Step = Callable[[Session, datetime], dict[str, int]]


def purge_maps(db: Session, now: datetime) -> dict[str, int]:
    from maps import api as maps_api

    return maps_api.purge_deleted_maps(db, now=now, older_than_days=MAP_RETENTION_DAYS)


def purge_notifications(db: Session, now: datetime) -> dict[str, int]:
    from notifications import api as notifications_api

    return notifications_api.purge_old(db, now=now)


def purge_guests(db: Session, now: datetime) -> dict[str, int]:
    from auth import api as auth_api

    return {"guests": auth_api.purge_inactive_guests(db, now)}


def purge_llm_calls(db: Session, now: datetime) -> dict[str, int]:
    from llm import api as llm_api

    return llm_api.purge_old(db, now=now)


STEPS: dict[str, Step] = {
    "maps": purge_maps,
    "notifications": purge_notifications,
    "guests": purge_guests,
    "llm_calls": purge_llm_calls,
}


def run_step(name: str, step: Step, session_factory, *, now: datetime, dry_run: bool) -> dict[str, int] | None:
    """한 단계를 자기 트랜잭션에서 돌린다. 실패하면 되돌리고 None."""
    db = session_factory()
    try:
        counts = step(db, now)
        if dry_run:
            db.rollback()
        else:
            db.commit()
        return counts
    except Exception as exc:
        db.rollback()
        logger.error("정리 단계 실패: %s (%s)", name, type(exc).__name__)
        return None
    finally:
        db.close()


def format_report(results: dict[str, dict[str, int] | None], *, dry_run: bool) -> str:
    lines = ["[dry-run] 지울 수" if dry_run else "지운 수"]
    for name, counts in results.items():
        if counts is None:
            lines.append(f"  {name}: 실패")
            continue
        total = sum(v for k, v in counts.items() if k != "deleted_maps")
        lines.append(f"  {name}: {total}행" + (f" (지도 {counts['deleted_maps']}개)" if "deleted_maps" in counts else ""))
    if dry_run:
        lines.append("(dry-run: 아무것도 지우지 않았다)")
    return "\n".join(lines)


def main(argv: list[str] | None = None, *, session_factory=None, now: datetime | None = None,
         steps: dict[str, Step] | None = None) -> int:
    steps = STEPS if steps is None else steps
    parser = argparse.ArgumentParser(prog="python -m maintenance.run", description="정기 정리를 한 번 돌린다.")
    parser.add_argument("--dry-run", action="store_true", help="지울 수만 보여 주고 지우지 않는다")
    parser.add_argument("--only", choices=list(steps), help="이 단계만 돌린다")
    args = parser.parse_args(argv)

    if session_factory is None:
        from common.database import SessionLocal

        session_factory = SessionLocal

    now = now or datetime.now(timezone.utc)
    selected = {args.only: steps[args.only]} if args.only else steps
    results = {
        name: run_step(name, step, session_factory, now=now, dry_run=args.dry_run) for name, step in selected.items()
    }
    print(format_report(results, dry_run=args.dry_run))
    return 1 if any(counts is None for counts in results.values()) else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
