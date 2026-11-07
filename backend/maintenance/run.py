"""정기 정리 러너(#168). 사용법:

    python -m maintenance.run [--dry-run] [--only maps|notifications|guests|llm_calls|idempotency|withdrawn|events|pins]

한 번 돌리면 ① 복구 기간이 지난 삭제 지도 ② 보존 기간이 지난 알림 ③ 오래 쓰지 않은 게스트 ④ 보존 기간이 지난 모델 호출
사용량(#870) ⑤ 보관 기간이 지난 「추천 받기」 멱등 키(run이 연결된 것, #811) ⑥ 복구 기간이 지난 탈퇴 계정의 개인정보(#857)
⑦ 재전송 창을 지난 실시간 이벤트(event_log, #1016) ⑧ 복구 기간이 지난 삭제 핀(#1063)을 차례로 지운다.
**기간은 여기 적지 않는다**(#1474) — 각 모듈이 자기 상수로 정하고, 정리 API는 `(db, now)`만 받는다. 기간을 바꿀 때는 그 모듈의
상수(`maps.core.TRASH_RETENTION`, `notifications.service.RETENTION_DAYS`, `auth.core.GUEST_INACTIVE_DAYS`,
`llm.usage.RETENTION_DAYS`, `recommend.core.IDEMPOTENCY_RETENTION`, `auth.core.ACCOUNT_RESTORE_DAYS`,
`realtime.service.PURGE_AFTER_HOURS`, `pins.core.TRASH_RETENTION_DAYS`) 하나만 고친다. `integration/test_purge_periods_one_place.py`가 지킨다.
실제 삭제는 각 모듈이 한다(`maps.api.purge_deleted_maps`, `notifications.api.purge_old`, `auth.api.purge_inactive_guests`,
`llm.api.purge_old`, `recommend.api.purge_idempotency_keys`, `auth.api.purge_withdrawn_accounts`, `realtime.api.purge_old_events`, `pins.api.purge_deleted_pins`) — 여기는 부르기만 한다.

- 단계마다 별도 세션·트랜잭션·커밋이다. 한 단계가 실패하면 그 단계만 되돌리고 다음으로 넘어간다. 실패는 로그에 단계
  이름과 에러 타입만 남긴다(메시지에는 사용자 데이터가 섞일 수 있다). 하나라도 실패하면 종료 코드는 1이다.
- 단계마다 건수가 0이 될 때까지 되풀이해 부른다(#1213). 각 모듈이 한 번에 지우는 양에 상한을 두므로(이벤트 로그, 탈퇴 계정,
  휴지통 핀) 쌓인 게 많으면 한 번으로 끝나지 않는다. 상한 값은 각 모듈 것이라 여기 복사하지 않고, 「한 번 더 불렀더니 또
  지웠다」로 남았는지 안다. 라운드마다 별도 트랜잭션·커밋이고, 라운드 수(`MAX_ROUNDS`)와 시간(`TIME_LIMIT_SECONDS`)이
  차도록 비지 않으면 적체(backlog)다 — 로그에 WARNING으로 남고, 개인정보 단계(`PERSONAL_DATA_STEPS`)는 ERROR다.
  남은 것은 다음 실행이 이어 지운다. 마지막 성공 시각은 로그 한 줄(`정리 마지막 성공`)로 남긴다. 로그에는 건수만 쓴다.
- `--dry-run`은 같은 삭제를 한 번 실행한 뒤 롤백해 지울 행 수만 보여 준다(롤백이라 되풀이하면 같은 행이 또 나온다).
- agent의 일일 정리(`agent.flows.daily_cleanup_if_due`)는 프로세스 안에서 도는 것이라 여기 넣지 않는다.
"""

import argparse
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

logger = logging.getLogger("maintenance")

MAX_ROUNDS = 20                 # 한 단계를 한 실행에서 되풀이하는 상한
TIME_LIMIT_SECONDS = 300        # 한 단계에 쓰는 시간 상한 — 라운드 사이에 확인한다
PERSONAL_DATA_STEPS = frozenset({"withdrawn"})   # 적체가 개인정보 보존 기간 위반이 되는 단계 — 적체 로그가 ERROR

Step = Callable[[Session, datetime], dict[str, int]]


def purge_pins(db: Session, now: datetime) -> dict[str, int]:
    from pins import api as pins_api

    return pins_api.purge_deleted_pins(db, now=now)


def purge_maps(db: Session, now: datetime) -> dict[str, int]:
    from maps import api as maps_api

    return maps_api.purge_deleted_maps(db, now=now)


def purge_notifications(db: Session, now: datetime) -> dict[str, int]:
    from notifications import api as notifications_api

    return notifications_api.purge_old(db, now=now)


def purge_guests(db: Session, now: datetime) -> dict[str, int]:
    from auth import api as auth_api

    return {"guests": auth_api.purge_inactive_guests(db, now)}


def purge_llm_calls(db: Session, now: datetime) -> dict[str, int]:
    from llm import api as llm_api

    return llm_api.purge_old(db, now=now)


def purge_idempotency_keys(db: Session, now: datetime) -> dict[str, int]:
    from recommend import api as recommend_api

    return {"idempotency_keys": recommend_api.purge_idempotency_keys(db, now=now)}


def purge_withdrawn(db: Session, now: datetime) -> dict[str, int]:
    from auth import api as auth_api

    return {"withdrawn_accounts": auth_api.purge_withdrawn_accounts(db, now)}


def purge_events(db: Session, now: datetime) -> dict[str, int]:
    from realtime import api as realtime_api

    return {"event_log": realtime_api.purge_old_events(db, now=now)}


STEPS: dict[str, Step] = {
    "maps": purge_maps,
    "notifications": purge_notifications,
    "guests": purge_guests,
    "llm_calls": purge_llm_calls,
    "idempotency": purge_idempotency_keys,
    "withdrawn": purge_withdrawn,
    "events": purge_events,
    "pins": purge_pins,
}


@dataclass
class StepResult:
    counts: dict[str, int] = field(default_factory=dict)   # 라운드를 합산한 건수
    rounds: int = 0
    backlog: bool = False    # 상한(라운드·시간)에 걸려 멈췄는데 마지막 라운드도 지웠다 → 남았을 수 있다
    failed: bool = False


def _add(total: dict[str, int], counts: dict[str, int]) -> None:
    for key, value in counts.items():
        total[key] = total.get(key, 0) + value


def run_step(name: str, step: Step, session_factory, *, now: datetime, dry_run: bool) -> StepResult:
    """한 단계를 라운드마다 자기 트랜잭션에서 돌린다. 건수가 0이면 비운 것이다. 실패하면 그 라운드만 되돌리고 failed.
    dry-run은 롤백이라 한 번만 부른다(되풀이하면 같은 행이 또 나온다). 그 경우 backlog는 알 수 없어 False다."""
    result = StepResult()
    started = time.monotonic()
    while True:
        db = session_factory()
        try:
            counts = step(db, now)
            if dry_run:
                db.rollback()
            else:
                db.commit()
        except Exception as exc:
            db.rollback()
            logger.error("정리 단계 실패: %s (%s)", name, type(exc).__name__)
            result.failed = True
            return result
        finally:
            db.close()
        result.rounds += 1
        _add(result.counts, counts)
        deleted = sum(counts.values())
        if dry_run or deleted == 0:
            return result
        if result.rounds >= MAX_ROUNDS or time.monotonic() - started >= TIME_LIMIT_SECONDS:
            result.backlog = True
            return result


def log_result(name: str, result: StepResult, *, dry_run: bool) -> None:
    """단계 결과를 로그로 남긴다 — 건수만(개인정보 없음). 적체는 WARNING, 개인정보 단계는 ERROR."""
    if result.failed:
        return
    total = sum(v for k, v in result.counts.items() if k != "deleted_maps")
    logger.info("정리 단계: %s 지움=%d 라운드=%d 적체=%s%s", name, total, result.rounds, "예" if result.backlog else "아니오",
                " (dry-run)" if dry_run else "")
    if result.backlog:
        level = logging.ERROR if name in PERSONAL_DATA_STEPS else logging.WARNING
        logger.log(level, "정리 적체: %s — 상한(라운드 %d, 시간 %ds)까지 지웠는데 더 남았을 수 있다. 다음 실행이 이어 지운다.",
                   name, MAX_ROUNDS, TIME_LIMIT_SECONDS)


def format_report(results: dict[str, StepResult], *, dry_run: bool) -> str:
    lines = ["[dry-run] 지울 수" if dry_run else "지운 수"]
    for name, result in results.items():
        if result.failed:
            lines.append(f"  {name}: 실패")
            continue
        counts = result.counts
        total = sum(v for k, v in counts.items() if k != "deleted_maps")
        line = f"  {name}: {total}행" + (f" (지도 {counts['deleted_maps']}개)" if "deleted_maps" in counts else "")
        if result.rounds > 1:
            line += f", {result.rounds}라운드"
        if result.backlog:
            line += " — 적체: 더 남았을 수 있다(다음 실행이 이어 지운다)"
        lines.append(line)
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
    results = {}
    for name, step in selected.items():
        results[name] = run_step(name, step, session_factory, now=now, dry_run=args.dry_run)
        log_result(name, results[name], dry_run=args.dry_run)
    print(format_report(results, dry_run=args.dry_run))
    ok = not any(result.failed for result in results.values())
    if ok and not args.dry_run:
        # 마지막 성공 시각 — 로그에서 이 줄을 찾으면 된다. --only 실행이면 그 단계만이라 단계 이름을 붙인다.
        logger.info("정리 마지막 성공: %s 단계=%s 적체=%s", datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    ",".join(results), ",".join(n for n, r in results.items() if r.backlog) or "없음")
    return 0 if ok else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
