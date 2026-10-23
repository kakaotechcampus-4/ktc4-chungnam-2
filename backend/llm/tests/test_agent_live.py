"""v2 에이전트 호출(#532) 실호출 확인 — 엘리스 ML API에 실제로 요청한다. 품질 평가가 아니라 계약 확인이다(평가는 #534).

확인하는 것: DiagnosisOutput 구조화 출력(strict)과 도구 인자 스키마(strict, null 허용 칸)가 400 없이 받아지고,
진단 대화가 도구 콜백을 거쳐 스키마에 맞는 답으로 끝나는지.
기본 실행에서는 제외된다(pytest.ini의 addopts `-m "not live"`). 돌릴 때:
    PINGO_TEST_DB=pingo_test_llm pytest -m live llm/tests/test_agent_live.py -v -s
"""

import pytest

from common.settings import settings
from llm import service
from llm.schemas import DiagnosisOutput

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (settings.elice_ml_api_base_url and settings.elice_ml_api_key),
        reason="ELICE_ML_API_BASE_URL / ELICE_ML_API_KEY가 없다",
    ),
]

STALL = {"signal_id": "s2", "diagnosis": "stall", "category": "음식점", "against_pin_ids": ["p1", "p2"]}


def _runner(calls):
    def run(call_id, name, args):
        calls.append((call_id, name, args))
        if name == "get_reasons":
            return {"items": [
                {"reaction_id": "r1", "pin_id": "p1", "type": "against", "text": "너무 매워요", "chips": [],
                 "member_alias": "m1", "updated_at": "2026-10-15T10:00:00+09:00"},
                {"reaction_id": "r2", "pin_id": "p2", "type": "against", "text": "여기는 좀 별로", "chips": [],
                 "member_alias": "m2", "updated_at": "2026-10-15T11:00:00+09:00"},
            ], "total": 2}
        if name == "get_readiness":
            return {"ready": True, "reason": None}
        if name == "get_map_overview":
            return {"dday": 5, "member_count": 3, "categories": {"음식점": {"pins": 2, "confirmed": 0}}}
        return {"error": "NOT_FOUND"}
    return run


def test_diagnose_tool_conversation_ends_in_schema():
    calls = []
    reply = service.agent_diagnose(STALL, tool_runner=_runner(calls), planner=service.real_diagnosis_planner)
    out = reply.result

    print("\n[live] tool calls:", [(c[0], c[1]) for c in calls])
    print("[live] diagnose:", out, reply.usage)
    assert isinstance(out, DiagnosisOutput), out
    assert out.signal_id == "s2" and out.diagnosis == "stall"
