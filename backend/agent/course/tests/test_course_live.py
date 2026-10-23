"""동선 에이전트 실호출 확인 — 엘리스 ML API(gpt-6-luna)에 실제로 요청한다. 품질 평가가 아니라 계약 확인이다.

확인하는 것: CourseTurn 구조화 출력(strict)이 400 없이 받아지고, 진짜 모델이 도식 2 지도에서 도구를 골라 쓰며 루프가 끝까지
도는지. 턴마다 무엇을 했는지 출력한다(-s). 기본 실행에서는 제외된다(pytest.ini의 addopts `-m "not live"`). 돌릴 때:
    PINGO_TEST_DOTENV=1 python -m pytest -m live agent/course/tests/test_course_live.py -v -s
턴당 요청 하나라 한 번 돌리면 요청이 많아야 MAX_TURNS(16)번이다.
"""

import pytest

from agent.course import loop
from agent.course.deps import ModelDecider
from agent.course.state import initial_state
from agent.course.tests.fixtures import COURSE, KNOWN_HOURS, TRUE_HOURS, trip
from common.settings import settings
from llm.api import real_course_turn_planner

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (settings.elice_ml_api_base_url and settings.elice_ml_api_key),
        reason="ELICE_ML_API_BASE_URL / ELICE_ML_API_KEY가 없다",
    ),
]


def test_real_model_runs_the_diagram_map():
    decider = ModelDecider(real_course_turn_planner)
    result = loop.run_loop(initial_state(trip(), KNOWN_HOURS, COURSE), decide=decider, hours=TRUE_HOURS)

    print(f"\n[live] outcome={result.outcome} model_turns={result.model_turns} baseline_turns={result.baseline_turns}"
          f" tokens(in,out)={decider.tokens} failures={[f.reason for f in decider.failures]}")
    for s in result.steps:
        status = "OK" if s.result.ok else s.result.error
        print(f"  {s.turn}. [{s.by}] {s.thought or '(' + str(s.thought_problem) + ')'} → {s.call} {status}")
    print(f"  best_course={result.best_course} soft={result.soft}")

    assert result.model_turns > 0, "모델 턴이 하나도 없다 — 스키마나 호출이 매번 실패했다"
    assert result.outcome in ("solved", "solved_with_checks", "unresolved")
