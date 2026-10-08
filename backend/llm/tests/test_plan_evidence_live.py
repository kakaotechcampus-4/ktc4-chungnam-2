"""② plan_evidence 실호출 확인 — 엘리스 ML API에 실제로 요청한다.

기본 실행에서는 제외된다(pytest.ini의 addopts `-m "not live"`) — 키 없이도 CI가 돌아야 한다.
돌릴 때: backend/.env에 ELICE_ML_API_BASE_URL / ELICE_ML_API_KEY / LLM_MODEL=gpt-6-luna가 있는 상태에서
    PINGO_TEST_DOTENV=1 PINGO_TEST_DB=pingo_test_llm pytest -m live llm/tests/test_plan_evidence_live.py -v -s
chat.completions.parse(strict JSON schema)가 400으로 거절되면 이 테스트가 실패한다 — 그때
call_planner를 response_format={"type": "json_object"} + 수동 Pydantic 검증으로 바꾼다(backend/llm/for_Root.md).
"""

import pytest

from common.settings import settings
from llm import client as llm_client
from llm import service

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (settings.elice_ml_api_base_url and settings.elice_ml_api_key),
        reason="ELICE_ML_API_BASE_URL / ELICE_ML_API_KEY가 없다",
    ),
]

REASONS = [
    {"author_id": "u1", "source": "reaction", "text": "갑각류 알러지가 있어서 새우 들어간 곳은 안 돼요", "badge": "required", "fact_key": None},
    {"author_id": "u2", "source": "reaction", "text": "조용하게 이야기할 수 있는 곳이면 좋겠어요", "badge": "preferred", "fact_key": None},
    {"author_id": "u3", "source": "reaction", "text": "그냥 별로예요", "badge": "preferred", "fact_key": None},
]


def test_strict_schema_is_accepted_by_the_api():
    """parse(strict JSON schema)가 400으로 거절되지 않는지 — 실패하면 BadRequest 여부가 메시지에 남는다."""
    output = llm_client.call_planner(llm_client.get_client(), REASONS)

    print("\n[live] model =", settings.llm_model)
    for reason in output.reasons:
        conditions = [(c.fact_key, c.wants) for c in reason.conditions]
        print("[live] raw:", reason.index, reason.text, "->", conditions, reason.circle_radius_m)
    assert len(output.reasons) == len(REASONS)


def test_plan_evidence_real_call_round_trip():
    groups = service.plan_evidence(REASONS, planner=service._real_evidence_planner())

    assert len(groups) == len(REASONS)
    for reason, group in zip(REASONS, groups):
        assert group, "입력 글마다 근거 줄이 1개 이상이어야 한다"
        assert {(ln.text, ln.badge, ln.author_id) for ln in group} == {(reason["text"], reason["badge"], reason["author_id"])}


def test_wants_fixture_cases_against_real_model():
    """#230 — 실제 Luna가 방향(wants)을 맞게 읽는지. 틀린 건 모아서 보여 주고 실패시킨다(#116에서 확인)."""
    import json
    from pathlib import Path

    cases = json.loads((Path(__file__).parent / "fixtures" / "wants_cases.json").read_text(encoding="utf-8"))
    reasons = [{"author_id": "u", "source": "reaction", "text": c["text"], "badge": c["badge"], "fact_key": None} for c in cases]

    # 서비스 경로여야 10개씩 묶음이 적용된다 — call_planner를 직접 부르면 게이트웨이 2000토큰 상한에 걸린다(#325).
    groups = service._model_planner(llm_client.get_client(), reasons)

    # 이 평가셋은 전부 조건 하나짜리 글이다 — 나뉘어 나오면 그것도 틀린 것이다(#419).
    wrong = [
        (c["text"], [(c["fact_key"], c["wants"])], [(o.fact_key, o.wants) for o in group])
        for c, group in zip(cases, groups)
        if [(o.fact_key, o.wants) for o in group] != [(c["fact_key"], c["wants"])]
    ]
    for text, want, got in wrong:
        print(f"[live] MISMATCH {text!r}: 기대 {want} / 실제 {got}")
    assert not wrong


def test_multi_key_cases_against_real_model():
    """#419 — 조건이 여럿인 글은 조건마다 줄로, 하나인 글은 나누지 않는다. 순서는 보지 않는다."""
    import json
    from pathlib import Path

    cases = json.loads((Path(__file__).parent / "fixtures" / "multi_key_cases.json").read_text(encoding="utf-8"))
    reasons = [{"author_id": "u", "source": "reaction", "text": c["text"], "badge": c["badge"], "fact_key": None} for c in cases]

    groups = service._model_planner(llm_client.get_client(), reasons)

    def got(group):
        return sorted((o.fact_key, o.wants) for o in group if o.fact_key is not None)

    wrong = [
        (c["text"], sorted(map(tuple, c["conditions"])), got(group))
        for c, group in zip(cases, groups)
        if got(group) != sorted(map(tuple, c["conditions"]))
    ]
    for text, want, actual in wrong:
        print(f"[live] MISMATCH {text!r}: 기대 {want} / 실제 {actual}")
    assert not wrong
