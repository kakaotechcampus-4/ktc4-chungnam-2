"""순수 함수 테스트 — DB 없이 직접 호출한다(docs/code-quality.md)."""

import pytest

from common.errors import AppError
from recommend import core
from recommend.models import RecommendRun


def _run(status: str) -> RecommendRun:
    return RecommendRun(map_id="map_1", category="음식점", requested_by="user_1", status=status)


def test_check_run_ready_passes_when_done():
    core.check_run_ready(_run("done"))  # 예외 없이 통과해야 한다


@pytest.mark.parametrize(
    "status", ["collecting_evidence", "awaiting_region_confirm", "executing", "failed"]
)
def test_check_run_ready_raises_not_ready_when_not_done(status):
    with pytest.raises(AppError) as exc_info:
        core.check_run_ready(_run(status))
    assert exc_info.value.code == "NOT_READY"
