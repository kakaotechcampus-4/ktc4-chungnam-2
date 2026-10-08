"""
실격 조건 계약 테스트 (#40) — 최우선 지표 "실격 조건 위반율 0%"(기획안 10절)를 CI에서 강제한다.

세 겹으로 지킨다.
1. 문서↔코드: docs/constraints.md 표의 `unknown_policy`와 recommend/constraints.py 레지스트리가 어긋나면 실패.
   (값 변경은 루트만 — 코드만 바꾸거나 문서만 바꾸면 여기서 잡힌다.)
2. 안전 조건 고정: 재료·알러지·매운맛·기름진 메뉴는 "모르면 제거"(exclude)여야 한다. 누가 pass로 바꾸면 실패.
3. 파이프라인: 안전 조건이 켜진 run에서 라벨이 unknown인 후보는 결과에 절대 나오지 않는다(가드레일 7·8).
   취향 조건(pass + needs_check)은 반대로 통과하되 needs_check 배지가 붙어야 한다.
"""

import re
import uuid
from pathlib import Path

import pytest

from auth.testing import session_cookie
from recommend import constraints
from recommend.core import apply_disqualifier_filters, build_check
from recommend.models import EvidenceLine

CONSTRAINTS_MD = Path(__file__).resolve().parents[2] / "docs" / "constraints.md"

# 안전 조건 — 틀리면 "못 먹는 걸 추천하는 사고"(docs/constraints.md "왜 unknown_policy가 조건마다 다른가").
# 이 집합은 의도적으로 하드코딩이다: 레지스트리에서 계산하면 레지스트리를 바꾸는 순간 테스트도 같이 바뀐다.
SAFETY_KEYS = frozenset({"contains_shellfish"})


def _doc_policies() -> dict[str, str]:
    """constraints.md의 조건 표 행에서 fact_key -> 'exclude'|'pass' 를 뽑는다. 행 첫 칸이 `key`로 시작하는 줄만 본다."""
    policies: dict[str, str] = {}
    for line in CONSTRAINTS_MD.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*`([a-z_]+)`", line)
        if not m or "unknown_policy" in line or m.group(1) == "fact_key":  # 헤더 행(음식점 채움 규칙 표는 unknown_policy 열이 없다)
            continue
        policies[m.group(1)] = "exclude" if "**exclude**" in line else "pass"
    return policies


def test_registry_matches_constraints_md_unknown_policy():
    doc = _doc_policies()
    mismatched, missing_in_doc = [], []
    for key, spec in constraints.HARD_REGISTRY.items():
        if key not in doc:
            missing_in_doc.append(key)
        elif doc[key] != spec.unknown_policy:
            mismatched.append((key, f"코드={spec.unknown_policy} 문서={doc[key]}"))
    assert not mismatched, f"unknown_policy가 문서와 다르다(값 변경은 루트만): {mismatched}"
    assert not missing_in_doc, f"문서에 없는 조건이 코드에 있다: {missing_in_doc}"
    for key in constraints.SOFT_FACT_KEYS:
        assert doc.get(key) == "pass", f"선호(soft) 조건 {key}는 pass여야 한다(5-1: 선호는 애초에 걸러내지 않는다)"


def test_every_condition_in_constraints_md_is_in_the_registry():
    """문서에만 있고 코드에 없는 조건(#171) — 라벨이 와도 조용히 버려진다. is_open·within_radius는 코드 판정이라 레지스트리 밖."""
    code_judged = {"is_open", "within_radius"}
    registered = set(constraints.HARD_REGISTRY) | constraints.SOFT_FACT_KEYS
    missing = sorted(set(_doc_policies()) - code_judged - registered)
    assert not missing, f"constraints.md에 있는데 레지스트리에 없는 조건: {missing}"


def test_safety_conditions_are_exclude_and_nothing_else_is():
    exclude_keys = {k for k, s in constraints.HARD_REGISTRY.items() if s.unknown_policy == "exclude"}
    assert exclude_keys == SAFETY_KEYS, (
        "안전 조건(exclude) 집합이 바뀌었다 — 안전 조건을 pass로 내리면 사고 위험, "
        f"새로 exclude를 늘리면 후보가 과하게 줄어든다. 코드={sorted(exclude_keys)} 기대={sorted(SAFETY_KEYS)}"
    )


@pytest.mark.parametrize("key", sorted(SAFETY_KEYS))
def test_unknown_safety_condition_disqualifies_the_candidate(key):
    check = build_check(key, constraints.HARD_REGISTRY[key].unknown_policy, known=False, value=None, passes=True)
    assert check.passed is False and check.confidence == "unknown"
    assert check.needs_check is False   # "확인해 달라"가 아니라 그냥 뺀 것
    assert apply_disqualifier_filters([[check]]) == [False]


@pytest.mark.parametrize("key", sorted(k for k, s in constraints.HARD_REGISTRY.items() if s.unknown_policy == "pass"))
def test_unknown_taste_condition_passes_with_needs_check_badge(key):
    check = build_check(key, "pass", known=False, value=None, passes=True)
    assert check.passed is True and check.needs_check is True
    assert apply_disqualifier_filters([[check]]) == [True]


def test_one_failed_check_disqualifies_even_if_the_rest_pass():
    """가드레일 9의 조건판 — 하나라도 불통과면 후보 전체 탈락."""
    ok = build_check("price_bucket", "pass", known=False, value=None, passes=True)
    bad = build_check("contains_shellfish", "exclude", known=False, value=None, passes=True)
    assert apply_disqualifier_filters([[ok, bad], [ok]]) == [False, True]


# ---------------------------------------------------------------- 파이프라인(실제 앱 + DB) ----

def _start_run_with_active_condition(a, b, db_session, fact_key: str, pin_body) -> str:
    """골든 패스와 같은 준비 뒤, 지정한 fact_key를 '꼭 지켜야 하는 조건'으로 켠 run을 만들어 execute까지 돌린다."""
    map_id = a.post("/maps", json={"title": "t", "start_date": "2026-11-01", "end_date": "2026-11-03",
                                   "region": {"label": "부산", "lat": 35.1796, "lng": 129.0756}}).json()["id"]
    inv = a.post(f"/maps/{map_id}/invite").json()
    assert b.post(f"/invites/{inv['token']}/accept").status_code == 200
    pins = []
    for key in ("seongsu-kalguksu", "seongsu-bunsik", "hongdae-ramen"):
        r = a.post(f"/maps/{map_id}/pins", json=pin_body(key))
        assert r.status_code == 201, r.text
        pins.append(r.json()["id"])
    for c, pid in ((a, pins[0]), (b, pins[0])):
        assert c.put(f"/pins/{pid}/reaction", json={"type": "like"}).status_code == 200
    for c in (a, b):
        assert c.put(f"/pins/{pins[1]}/reaction", json={"type": "against", "reason_text": "별로"}).status_code == 200
    run = a.post(f"/maps/{map_id}/runs", json={"category": "음식점"})
    assert run.status_code == 202, run.text
    run_id = run.json()["id"]
    db_session.add(EvidenceLine(
        id=uuid.uuid4(), run_id=uuid.UUID(run_id), author_id="user_a", source="manual",
        text=f"{fact_key} 조건", badge="required", fact_key=fact_key, is_active=True,
    ))
    db_session.commit()
    assert a.post(f"/runs/{run_id}/regions/confirm", json={}).status_code == 200
    assert a.post(f"/runs/{run_id}/execute").status_code == 202
    return run_id


@pytest.fixture()
def clients(app_client, two_users):
    from fastapi.testclient import TestClient
    a = TestClient(app_client.app, cookies=session_cookie("user_a"))
    b = TestClient(app_client.app, cookies=session_cookie("user_b"))
    yield a, b
    a.close()
    b.close()


@pytest.mark.parametrize("key", sorted(SAFETY_KEYS & set(constraints.hard_fact_keys_for("음식점"))))
def test_pipeline_never_recommends_a_place_whose_safety_label_is_unknown(clients, db_session, key, pin_body):
    a, b = clients
    run_id = _start_run_with_active_condition(a, b, db_session, key, pin_body)
    result = a.get(f"/runs/{run_id}/result")
    # dev 장소 정보는 라벨이 전부 unknown이다 → 안전 조건이 켜져 있으면 단 한 곳도 통과하면 안 된다.
    if result.status_code == 200:
        assert result.json()["candidates"] == [], f"{key}가 unknown인데 후보가 나왔다 — 실격 위반"
    else:
        assert result.status_code == 404 and result.json()["code"] == "NO_RESULTS"


def test_pipeline_keeps_unknown_taste_candidates_but_flags_them(clients, db_session, pin_body):
    a, b = clients
    run_id = _start_run_with_active_condition(a, b, db_session, "price_bucket", pin_body)
    result = a.get(f"/runs/{run_id}/result")
    assert result.status_code == 200
    candidates = result.json()["candidates"]
    assert candidates, "취향 조건(pass + needs_check)이 unknown이라고 후보를 지우면 안 된다"
    for candidate in candidates:
        flagged = [c for c in candidate["checks"] if c["fact_key"] == "price_bucket"]
        assert flagged and all(c["needs_check"] for c in flagged)
