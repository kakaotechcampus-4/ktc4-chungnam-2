"""관찰 tick 명령(#812). 사용법:

    python -m agent.tick

`flows.run_tick`을 한 번 돌리고 끝난다. 서버 cron이 5분마다 부른다(`deploy/crontab`). 두 번 겹쳐 돌아도 안전하다 —
지도마다 lease를 잡고(`service.claim_maps`), 해제와 저장은 그 lease의 token이 아직 같을 때만 한다.
실패한 지도는 run_tick이 지도마다 기록하고 넘어간다. 여기서 예외가 올라오면(DB 연결 등) 종료 코드 1이다.
"""

import logging
import sys
from datetime import datetime, timezone

from agent import flows

log = logging.getLogger("pingo.agent")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        flows.run_tick(datetime.now(timezone.utc))
    except Exception as exc:   # noqa: BLE001 — 클래스 이름만 남긴다(메시지에 입력값이 실릴 수 있다)
        log.error("agent tick 실패 error=%s", type(exc).__name__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
