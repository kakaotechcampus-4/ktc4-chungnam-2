"""동선 에이전트가 다른 모듈에 기대는 것을 프로토콜로 좁혀 둔다(recommend/ports.py와 같은 패턴).

영업시간은 places가 자체 DB로 줄 예정이다(명세 14.1, 데이터 담당 납품 대기). 그전까지는 테스트·개발에서
FixtureOpeningHours를 쓴다. 실구현은 places.api.get_opening_hours를 감싸 이 Protocol만 만족하면 된다.
"""

from typing import Mapping, Optional, Protocol, Sequence

from agent.course.core import DayStatus


class OpeningHoursGateway(Protocol):
    def get_opening_hours(self, place_ids: Sequence[str]) -> Mapping[str, Optional[Mapping[int, DayStatus]]]:
        """place_id → 요일(월=0) → 상태. 모르는 장소는 None, 모르는 요일은 빠지거나 unknown이다.
        값을 지어내지 않는다 — 모르면 모른다고 돌려준다."""
        ...


class FixtureOpeningHours:
    """고정 표를 돌려주는 개발용 구현. 표에 없는 장소는 None(모름)."""

    def __init__(self, table: Mapping[str, Mapping[int, DayStatus]]):
        self._table = dict(table)

    def get_opening_hours(self, place_ids: Sequence[str]) -> Mapping[str, Optional[Mapping[int, DayStatus]]]:
        return {pid: self._table.get(pid) for pid in place_ids}
