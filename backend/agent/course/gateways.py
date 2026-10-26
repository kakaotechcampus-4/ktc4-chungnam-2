"""AI 코스 짜기의 배선 — 영업시간 게이트웨이, 모델 planner, 세션 팩토리를 한 곳에서 고른다(agent/deps.py, recommend/deps.py와 같은 방식).

- **영업시간(`opening_hours_gateway`)**: `places.api.get_week_open_status`(place_hours를 배치로 읽어 요일 단위로 판정, #747)를 감싼
  `PlacesOpeningHours`다. place_hours 행이 없는 장소는 None(모름)이라 「확인 필요」(`unknown_hours="check"`)로 남고 위반으로 세지 않는다.
  `NullOpeningHours`(전부 모름)는 테스트용이다.
- **모델(`get_course_llm`)**: LLM_MODE=dev는 모델을 부르지 않는다(요청 한 줄은 "반영하지 못했어요"로 남고 코스는 코드 기준선이 짠다).
  real은 목표 세우기와 지휘 턴에 엘리스 모델(`gpt-6-luna`)을 쓴다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from agent.course.core import DayStatus
from agent.course.ports import OpeningHoursGateway
from common.database import SessionLocal
from common.settings import settings
from llm import api as llm_api
from places import api as places_api


class PlacesOpeningHours:
    """places.api가 읽은 place_hours로 요일별 상태를 돌려준다. 행이 없는 장소는 None(모름) — 값을 지어내지 않는다.
    판정 규칙은 places.core가 한 곳에서 정한다. 호출마다 짧은 세션을 places.api가 연다."""

    def get_opening_hours(self, place_ids: Sequence[str]) -> Mapping[str, Optional[Mapping[int, DayStatus]]]:
        found = places_api.get_week_open_status(list(place_ids))
        return {pid: found.get(pid) for pid in place_ids}


class NullOpeningHours:
    """영업시간을 하나도 모르는 구현(테스트용) — 모든 장소가 None(모름)이다."""

    def get_opening_hours(self, place_ids: Sequence[str]) -> Mapping[str, Optional[Mapping[int, DayStatus]]]:
        return {pid: None for pid in place_ids}


def opening_hours_gateway() -> OpeningHoursGateway:
    """영업시간 게이트웨이를 만드는 유일한 자리."""
    return PlacesOpeningHours()


@dataclass(frozen=True)
class CourseLlm:
    """None이면 그 자리에서 모델을 부르지 않는다. goals_planner가 None이면 요청 한 줄은 목표가 되지 못한다."""

    goals_planner: Optional[Callable[[Mapping[str, Any]], Any]]
    direct_planner: Optional[Callable[[Mapping[str, Any]], Any]]


def _dev_course_llm() -> CourseLlm:
    return CourseLlm(goals_planner=None, direct_planner=None)


def _real_course_llm() -> CourseLlm:
    return CourseLlm(
        goals_planner=llm_api.real_course_goals_planner, direct_planner=llm_api.real_course_direct_planner,
    )


def get_course_llm() -> CourseLlm:
    """LLM_MODE로 고른다. settings가 prod에서 dev를 막으므로 여기서 따로 가드하지 않는다. select()(common.adapters)로 레지스트리에
    올리지 않는 이유: 이 포트는 dev도 real도 실구현이라 "실구현 없는 포트" 목록(common/tests/test_adapter_assembly.py)에 넣을 게 없다."""
    return _real_course_llm() if settings.llm_mode == "real" else _dev_course_llm()


def get_session_factory() -> Callable[[], Session]:
    """백그라운드 실행이 짧은 세션을 여러 번 여는 데 쓴다(모델 호출 중에는 연결을 잡지 않는다). 테스트는 이 의존성을 바꾼다."""
    return SessionLocal


def get_opening_hours_gateway() -> OpeningHoursGateway:
    return opening_hours_gateway()


LlmDep = Depends(get_course_llm)
SessionFactoryDep = Depends(get_session_factory)
OpeningHoursDep = Depends(get_opening_hours_gateway)
