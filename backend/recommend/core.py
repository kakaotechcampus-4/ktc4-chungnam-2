"""
기능형 코어 — 순수 함수만 둔다(docs/code-quality.md). DB·게이트웨이를 건드리지 않고,
이미 로드된 값을 받아 판정·조립만 한다. #108(코어 파이프라인) 범위의 순수 함수 전체를
여기 모은다: check_readiness/assemble_evidence/region_signature/apply_disqualifier_filters/
funnel_counts/widen_radius/check_retry_limit + 이들을 뒷받침하는 원(Circle) 계산.

멤버십·작성자(author) 판정은 여기 두지 않는다 — authz.resolve_principal(gateway 호출, I/O)와
authz.can()이 이미 그 판정을 갖고 있다(authz/policy.py::AUTHOR_CONSTRAINED_ACTIONS에
recommend.publish가 등록됨). 이 파일에 남는 건 run/candidate/evidence/region 자체의 상태
판정과 순수 계산뿐이다.
"""

import hashlib
import math
from dataclasses import dataclass
from typing import Any, Collection, Mapping, Sequence

from common.errors import AppError
from common.geo import WALKING_SPEED_M_PER_MIN, haversine_distance_m
from places.schemas import FactLabel
from recommend import constraints
from recommend.models import RecommendRun
from recommend.ports import Circle
from recommend.schemas import Check

ATTEMPT_LIMIT = 5  # docs/data-model.md #31 확정: 개인 단위, 카테고리 무관, 상한 5회
# 반경 넓히기 상수 — docs/constraints.md "반경 넓히기 상수" 절 그대로(조정 가능한 상수, 바꿀
# 때 루트에게 알린다). 기본값 원은 도보 15분에서 시작해 한 번에 5분씩, 30분까지.
DEFAULT_RADIUS_WALK_MIN = 15
WIDEN_STEP_MIN = 5
WIDEN_LIMIT_MIN = 30


def check_run_ready(run: RecommendRun) -> None:
    """run.status가 'done'이 아니면 409 NOT_READY.

    done이 아닌 나머지 상태(collecting_evidence/awaiting_region_confirm/executing/failed)를
    전부 동일하게 취급한다 — mentor-review-plan.md 실패 매핑 표는 "run이 아직 완료 안 됨"
    하나로만 다뤘다. failed를 다른 코드로 구분할지는 이 계획 범위 밖의 결정이라 루트 확인이
    필요하다(for_Root.md에 기록)."""
    if run.status != "done":
        raise AppError("NOT_READY")


def required_count(member_count: int) -> int:
    """ceil(N/2) — docs/api-spec.yaml Readiness.required_count. N=현재 참여 중인(지도 구성원)
    인원 수로 확정(#32, 2026-09-23) — 호출부(maps.api.count_members)가 그 값을 넘긴다.
    member_count<=0은 지도가 생성 시점부터 항상 최소 1명(만든 사람)을 구성원으로 두어 실제
    경로에서 도달하지 않는 방어 코드다."""
    if member_count <= 0:
        return 0
    return math.ceil(member_count / 2)


def check_readiness(answered_count: int, member_count: int) -> dict:
    """5-4 추천 버튼 활성화 판정. api-spec.yaml Readiness와 같은 모양의 dict를 돌려준다."""
    required = required_count(member_count)
    return {"ready": answered_count >= required, "answered_count": answered_count, "required_count": required}


def assemble_evidence(reaction_lines: list[dict], manual_lines: list[dict]) -> list[dict]:
    """② 사유 → 실격/선호/반경 구조화 이후, 근거 리스트 하나로 병합한다 — 실제 구조화(모델
    호출)는 llm.service.plan_evidence가 하고(service.py에서 호출, 여기는 그 결과를 받기만
    한다) 이 함수는 순수 병합/정렬만 한다.

    reaction_lines: badge='required'(반대) 등 반응에서 파생된 근거(source='reaction').
    manual_lines: 사용자가 직접 추가한 근거(source='manual', badge='reference').
    둘 다 EvidenceLine 생성에 바로 쓸 수 있는 dict(author_id/source/text/badge/fact_key/...)
    shape라고 전제한다 — DB insert 자체는 service.py가 한다(이 함수는 순서만 정한다: 반응
    유래 근거를 먼저, 수동 추가를 뒤에 — "-"로 뺄 수 있는 자기 근거를 찾기 쉽게 원 작성
    순서를 보존한다)."""
    return [*reaction_lines, *manual_lines]


def circles_all_overlap(circles: list[Circle]) -> bool:
    """모든 원 쌍이 겹치면 하나의 지역으로 병합 가능(자동 확인 — 5-6-1 "사람이 쓴 반경 사유
    끼리 안 겹칠 때만" region/confirm 호출이 실제로 필요해진다). 0~1개는 겹칠 대상이 없으므로
    항상 True."""
    if len(circles) <= 1:
        return True
    for i in range(len(circles)):
        for j in range(i + 1, len(circles)):
            a, b = circles[i], circles[j]
            distance = haversine_distance_m(a.anchor_lat, a.anchor_lng, b.anchor_lat, b.anchor_lng)
            if distance > a.radius_m + b.radius_m:
                return False
    return True


def region_signature(circles: list[Circle]) -> str:
    """5-6-1 겹침 판정 서명. 활성 반경 사유 집합이 바뀌면(추가/수정/비활성) 값이 달라진다 —
    좌표는 소수 6자리(약 11cm 단위)로 반올림해 부동소수 잡음이 서명을 흔들지 않게 한다.
    순서 무관(정렬 후 해시) — 같은 원 집합이면 입력 순서가 달라도 같은 서명이 나온다."""
    parts = sorted(f"{c.anchor_lat:.6f},{c.anchor_lng:.6f},{c.radius_m}" for c in circles)
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def merge_circles(circles: list[Circle]) -> Circle:
    """겹치는(또는 하나뿐인) 원들을 포괄원 하나로 압축한다 — 중심은 앵커 좌표 평균, 반경은
    그 중심에서 각 원의 경계까지 거리 중 최댓값(근사 최소 포괄원, 정확한 smallest enclosing
    circle은 아니다 — v1 범위에서는 이 정도 근사로 충분하다고 판단)."""
    if not circles:
        raise ValueError("circles가 비어 있습니다")
    center_lat = sum(c.anchor_lat for c in circles) / len(circles)
    center_lng = sum(c.anchor_lng for c in circles) / len(circles)
    radius = max(
        haversine_distance_m(center_lat, center_lng, c.anchor_lat, c.anchor_lng) + c.radius_m
        for c in circles
    )
    return Circle(anchor_lat=center_lat, anchor_lng=center_lng, radius_m=round(radius))


def radius_m_for_walk_min(walk_min: int) -> int:
    """기본값 원의 도보 시간(분) → 반경(m). common.geo의 보정계수를 그대로 쓴다."""
    return walk_min * WALKING_SPEED_M_PER_MIN


def next_default_radius_walk_min(current_walk_min: int) -> int:
    """반경 넓히기(5-6-1, 가드레일4) — 기본값 원의 다음 도보 시간. 이미 상한이면 409
    WIDEN_LIMIT — 상한을 넘겨 완화하는 건 AI도 코드도 하지 않는다(사람이 「근거 고치기」/
    「직접 찍기」로 간다). "사람이 명시한 원은 넓히지 않는다"는 구분은 이 함수가 아니라 호출부가
    넘기는 대상에 달려 있다(flows.widen_run)."""
    if current_walk_min >= WIDEN_LIMIT_MIN:
        raise AppError("WIDEN_LIMIT", detail={"default_radius_walk_min": current_walk_min})
    return min(current_walk_min + WIDEN_STEP_MIN, WIDEN_LIMIT_MIN)


def is_within_any_region(lat: float, lng: float, regions: list[Circle]) -> bool:
    """5-6 1단계(반경) — 확정된 지역(들) 중 하나라도 안에 있으면 통과. 지역이 여러 개(각각
    찾기, accept_union)면 OR 조건이다."""
    return any(
        haversine_distance_m(region.anchor_lat, region.anchor_lng, lat, lng) <= region.radius_m
        for region in regions
    )


def build_check(fact_key: str, unknown_policy: str, *, known: bool, value, passes: bool) -> Check:
    """docs/constraints.md 조건 하나에 대한 Check 조립 — unknown_policy 분기를 여기 한 곳에
    고정한다(가드레일 8: "판정 불확실은 조건 종류에 따라 다르게 처리한다").

    - known=False & unknown_policy='exclude' → passed=False(실격), needs_check=False(불확실
      해서 뺀 것이지 "확인해 달라"는 배지가 아니다 — 안전 조건이므로 절대 통과시키지 않는다).
    - known=False & unknown_policy='pass'(+needs_check) → passed=True, needs_check=True.
    - known=True → passed는 실제 값 기반 통과 여부(호출부가 계산해 넘긴다), needs_check=False.
    """
    if not known:
        if unknown_policy == "exclude":
            return Check(fact_key=fact_key, label="확인 불가", passed=False, confidence="unknown", needs_check=False)
        return Check(fact_key=fact_key, label="확인 필요", passed=True, confidence="unknown", needs_check=True)
    return Check(fact_key=fact_key, label=str(value), passed=passes, confidence="known", needs_check=False)


def resolve_label(labels: Sequence[FactLabel], fact_key: str) -> tuple[bool, Any]:
    """place_facts 라벨에서 fact_key 하나의 (known 여부, 값). 라벨이 없거나 confidence가 unknown이거나
    known인데 값이 비어 있으면 unknown으로 본다 — 값 없는 known을 통과 쪽으로 읽지 않는다(안전 조건은
    unknown_policy=exclude라 build_check가 후보를 내린다, 가드레일 8)."""
    for label in labels:
        if label.fact_key == fact_key:
            known = label.confidence == "known" and label.value is not None
            return known, label.value if known else None
    return False, None


def apply_disqualifier_filters(candidate_checks: list[list[Check]]) -> list[bool]:
    """5-6 3단계(실격 조건) + 가드레일9("한 명이라도 실격이면 후보에서 내린다"의 조건판
    버전 — 여기서는 "체크 하나라도 불통과면 후보 전체 탈락"). 후보별 checks 리스트를 받아
    후보별 통과 여부(bool) 리스트를 그대로 반환한다 — 실제 제거는 호출부(service.py)가 이
    bool로 후보 리스트를 필터링한다(이 함수는 후보 객체 자체를 모른다 — 순수하게 checks만
    본다).

    hard 체크만 본다. 선호(soft) 라벨(`constraints.SOFT_FACT_KEYS`)의 passed는 "실격 아님"이 아니라
    그 라벨의 참/거짓값이라(예: quiet=False → passed=False), 판정에 섞으면 아무도 원하지 않은
    조건 때문에 후보가 전멸한다(#208). soft 체크는 선호 점수(score_candidates)의 입력으로만 쓴다."""
    return [
        all(check.passed for check in checks if check.fact_key not in constraints.SOFT_FACT_KEYS)
        for checks in candidate_checks
    ]


def checks_to_show(checks: Sequence[Check], wanted_fact_keys: Collection[str]) -> list[Check]:
    """후보 저장·응답·게시(pins 복사)에 남길 체크(#216, 가드레일 5). hard 체크는 전부, soft 체크는
    사람이 원한 키(`wanted_fact_keys`)일 때만 — known 여부와 무관하다(원한 키가 unknown이면
    needs_check로 남는다). 아무도 말하지 않은 soft는 known이어도 싣지 않는다: cuisine_* 10개처럼
    한 곳당 9개가 거짓인 키가 실패 체크로 줄줄이 보이고, 모름은 「확인 필요」만 늘린다.
    점수 계산은 이 함수를 거치지 않은 전체 체크를 쓴다."""
    return [
        check for check in checks
        if check.fact_key not in constraints.SOFT_FACT_KEYS or check.fact_key in wanted_fact_keys
    ]


def funnel_counts(stage_removed: list[tuple[str, int]]) -> list[dict]:
    """5-6 깔때기 표 — (라벨, 이번 단계에서 제거된 수) 쌍의 리스트를 api-spec.yaml
    FunnelEntry 모양으로 그대로 옮긴다."""
    return [{"label": label, "removed_count": removed} for label, removed in stage_removed]


def check_retry_limit(attempt_no: int) -> None:
    """재시도 상한(#31: 개인 단위, 카테고리 무관, 상한 5회). attempt_no는 다음 시도를 실행하기
    *전* 현재까지의 시도 횟수 — 이미 상한에 도달했으면(이번이 6번째가 될 것이므로) 429."""
    if attempt_no >= ATTEMPT_LIMIT:
        raise AppError("RETRY_LIMIT", detail={"attempt_no": attempt_no})


# ============================================================================
# #112 — 선호 순위 점수 계산과 상위 3곳 선정 (#99 후속, ③-b)
#
# 규칙 정본은 이슈 #112 본문("할 일" 절, docs/constraints.md에 아직 옮겨지지 않은 상태 —
# for_Root.md에 문서 갭으로 보고). 아래 세 함수가 이슈의 1~3단계에 각각 대응한다.
# ============================================================================


@dataclass(frozen=True)
class HeartedPlace:
    """♥ 반응을 받은 핀 하나 — 그 핀의 라벨(checks)과 ♥를 누른 구성원 user_id 집합.

    checks에 fact_key가 없거나(is_open 등 core.py가 직접 채우는 값) confidence='unknown'인
    항목은 선호 기준·점수 계산 어디에도 기여하지 않는다(조사 안 된 라벨은 0점, 감점도 없다)."""

    checks: list[Check]
    member_ids: frozenset[str]


@dataclass(frozen=True)
class ScoredCandidate:
    """3단계(상위 N곳 고르기) 입력 — 후보 하나의 점수·소속 동네·좌표."""

    place_id: str
    score: int
    region_label: str
    lat: float
    lng: float


def build_preference_criteria(
    hearted_places: Sequence[HeartedPlace],
    *,
    excluded_fact_keys: frozenset[str],
    disqualifying_fact_keys: Sequence[str],
    preferred_authors: Mapping[str, frozenset[str]],
) -> dict[str, bool]:
    """1단계 — 선호 기준 만들기(이슈 #112 ①~⑤ 순서 그대로).

    ① ♥ 받은 핀들의 라벨(checks)을 전부 모은다 — confidence='known'인 것만(②와 별개로,
       조사 안 된 라벨은 애초에 신호가 없다).
    ② 참/거짓으로 답할 수 없는 라벨(가격대·수용 인원, `excluded_fact_keys` — 정본은
       constraints.VALUE_COMPARISON_UNSUPPORTED)은 뺀다.
    ③ ♥ 받은 "장소" 개수(사람 수가 아니다)로 값이 갈리면 많은 쪽을 택한다. 정확히 반반이면
       —이슈 본문이 이 경우를 정하지 않아 이 세션이 임시로 정함(for_Root.md 보고)— 신호가
       없다고 보고 그 라벨 자체를 기준에서 뺀다.
    ④ 이번 run에서 활성 실격 사유로 이미 쓰인 라벨(`disqualifying_fact_keys`)은 뺀다 — 통과한
       후보 전부가 이미 같은 값이라 점수 차이를 못 만든다.
    ⑤ 구성원이 직접 쓴 선호 사유의 라벨(`preferred_authors`의 키 — fact_key → 그 사유를 쓴
       구성원들)은 True로 추가한다(②·④ 제외 대상이면 마찬가지로 뺀다) — ③의 다수결 결과보다
       우선한다(명시적 선호이므로).

    소프트 키(`constraints.SOFT_FACT_KEYS`)만 쓴다. 하드 체크의 passed는 "실격 아님"이라 라벨
    값과 뜻이 다르므로 선호 신호로 섞으면 안 된다(①~⑤ 전부에 적용).

    반환값은 fact_key -> "이 팀이 좋아하는 값" 매핑이다. 값이 False로 확정된 항목은 2단계에서
    "양쪽 다 참일 때만 점수를 준다"는 규칙 때문에 점수에 기여하지 않지만, 어떤 라벨이 왜
    후보에서 빠졌는지 추적할 수 있도록 그대로 남겨둔다."""
    true_counts: dict[str, int] = {}
    false_counts: dict[str, int] = {}
    for place in hearted_places:
        for check in place.checks:
            if check.fact_key not in constraints.SOFT_FACT_KEYS:
                continue
            if check.fact_key in excluded_fact_keys or check.fact_key in disqualifying_fact_keys:
                continue
            if check.confidence != "known":
                continue
            counts = true_counts if check.passed else false_counts
            counts[check.fact_key] = counts.get(check.fact_key, 0) + 1

    criteria: dict[str, bool] = {}
    for fact_key in set(true_counts) | set(false_counts):
        true_count, false_count = true_counts.get(fact_key, 0), false_counts.get(fact_key, 0)
        if true_count == false_count:
            continue  # 동점 — 신호 없음(위 ③ docstring)
        criteria[fact_key] = true_count > false_count

    for fact_key in preferred_authors:
        if fact_key not in constraints.SOFT_FACT_KEYS:
            continue
        if fact_key in excluded_fact_keys or fact_key in disqualifying_fact_keys:
            continue
        criteria[fact_key] = True  # ⑤ — 명시적 선호가 ③의 다수결보다 우선한다

    return criteria


def _member_support(
    hearted_places: Sequence[HeartedPlace],
    preferred_authors: Mapping[str, frozenset[str]] | None = None,
) -> dict[str, tuple[frozenset[str], frozenset[str]]]:
    """fact_key마다 (지지 구성원 집합, 반대 구성원 집합) — 지지는 그 값을 True로 가진 곳에 ♥한
    구성원 + 그 fact_key를 선호 사유로 직접 쓴 구성원(♥ 이력이 없어도 명시적 선호는 지지다),
    반대는 False로 가진 곳에 ♥한 구성원. "구성원 단위로 센다"(한 사람이 같은 값의 장소 여러
    곳에 ♥해도, ♥하고 사유도 써도 1명)를 집합으로 자연스럽게 보장한다. 소프트 키만 쓴다."""
    supporting: dict[str, set[str]] = {}
    opposing: dict[str, set[str]] = {}
    for place in hearted_places:
        for check in place.checks:
            if check.fact_key not in constraints.SOFT_FACT_KEYS or check.confidence != "known":
                continue
            bucket = supporting if check.passed else opposing
            bucket.setdefault(check.fact_key, set()).update(place.member_ids)
    for fact_key, authors in (preferred_authors or {}).items():
        if fact_key in constraints.SOFT_FACT_KEYS:
            supporting.setdefault(fact_key, set()).update(authors)
            # 그 라벨을 선호 사유로 직접 쓴 사람은 같은 라벨의 반대 집합에 있어도(예전에 ♥한 곳이
            # 거짓이었던 경우) 반대로 세지 않는다 — 안 그러면 한 사람이 지지와 반대로 동시에
            # 잡혀 +1−1로 상쇄된다(#112 후속). 말로 쓴 선호가 ♥ 이력보다 우선이다.
            if fact_key in opposing:
                opposing[fact_key] -= set(authors)
    return {
        fact_key: (frozenset(supporting.get(fact_key, ())), frozenset(opposing.get(fact_key, ())))
        for fact_key in set(supporting) | set(opposing)
    }


def score_candidates(
    candidate_checks_by_place: Mapping[str, list[Check]],
    hearted_places: Sequence[HeartedPlace],
    criteria: Mapping[str, bool],
    preferred_authors: Mapping[str, frozenset[str]] | None = None,
) -> dict[str, int]:
    """2단계 — 후보마다 점수 매기기(이슈 #112).

    criteria[fact_key] is True이고 후보 자신도 그 라벨이 known+True일 때만("양쪽 다 참일 때만")
    점수를 준다. 더하는 값은 (그 라벨=True인 곳에 ♥한 구성원 수 − False인 곳에 ♥한 구성원 수).
    조사 안 된(unknown) 라벨은 0점 — 감점도 없다."""
    support = _member_support(hearted_places, preferred_authors)
    empty: tuple[frozenset[str], frozenset[str]] = (frozenset(), frozenset())
    scores: dict[str, int] = {}
    for place_id, checks in candidate_checks_by_place.items():
        total = 0
        for check in checks:
            if check.confidence != "known" or not check.passed:
                continue
            if criteria.get(check.fact_key) is not True:
                continue
            supporting, opposing = support.get(check.fact_key, empty)
            total += len(supporting) - len(opposing)
        scores[place_id] = total
    return scores


def build_member_fulfillment(
    candidate_checks: list[Check],
    hearted_places: Sequence[HeartedPlace],
    criteria: Mapping[str, bool],
    preferred_authors: Mapping[str, frozenset[str]] | None = None,
) -> dict:
    """가드레일5 "구성원 충족 집계" — api-spec.yaml `MemberFulfillment` 모양 그대로
    `{satisfied, total, by_member}`을 돌려준다.

    - **total** = 조건을 남긴 구성원 수. 조건 = 이번 선호 기준(`criteria`가 True인 fact_key)
      중 그 구성원이 지지한(그 값의 장소에 ♥했거나 선호 사유로 쓴) 것. 조건이 하나도 없는
      구성원은 집계 대상이 아니다(♥만 누르고 기준에 안 든 사람, 반대만 한 사람).
    - **satisfied** = 자기 조건을 *전부* 이 후보가 known+참으로 충족한 구성원 수. 일부만
      맞으면 충족으로 세지 않는다(구성원 만족을 부풀리지 않는다).
    - 점수(`score_candidates`)와 같은 "양쪽 다 참" 조건을 재사용한다."""
    support = _member_support(hearted_places, preferred_authors)
    met = {c.fact_key for c in candidate_checks if c.confidence == "known" and c.passed}
    conditions: dict[str, set[str]] = {}
    for fact_key, wanted in criteria.items():
        if wanted is not True:
            continue
        supporting, _opposing = support.get(fact_key, (frozenset(), frozenset()))
        for member_id in supporting:
            conditions.setdefault(member_id, set()).add(fact_key)
    by_member = [
        {"user_id": member_id, "satisfied": fact_keys <= met}
        for member_id, fact_keys in sorted(conditions.items())
    ]
    return {
        "satisfied": sum(1 for entry in by_member if entry["satisfied"]),
        "total": len(by_member),
        "by_member": by_member,
    }


def build_reason(
    candidate_checks: Sequence[Check], criteria: Mapping[str, bool], member_fulfillment: Mapping,
) -> str:
    """Candidate.reason — 실제로 통과한 체크와 충족한 선호 라벨에서 조립한 한 줄(가드레일 5).
    모델을 부르지 않는다. 두 종류만 말한다: 1) 이번 run의 활성 실격 조건 중 known으로 통과한
    것 2) 선호 기준(criteria) 중 이 후보가 known+참인 것(+ 몇 명이 충족했는지). 표시 이름이
    없는 키와 값 비교를 못 하는 키(price_bucket)는 말하지 않는다 — 안 본 것을 통과했다고 하지
    않기 위해서다. 말할 근거가 하나도 없으면 고른 과정 그대로를 적는다(추천 근거를 지어내지
    않는다)."""
    known_passed = {c.fact_key for c in candidate_checks if c.confidence == "known" and c.passed}
    disqualifier_labels = [
        constraints.PASSED_LABELS[c.fact_key]
        for c in candidate_checks
        if c.fact_key in constraints.HARD_REGISTRY
        and c.fact_key not in constraints.VALUE_COMPARISON_UNSUPPORTED
        and c.fact_key in constraints.PASSED_LABELS
        and c.confidence == "known" and c.passed
    ]
    preference_labels = [
        constraints.PASSED_LABELS[fact_key]
        for fact_key in sorted(criteria)
        if criteria[fact_key] is True and fact_key in known_passed and fact_key in constraints.PASSED_LABELS
        and fact_key in constraints.SOFT_FACT_KEYS
    ]
    parts: list[str] = []
    if disqualifier_labels:
        parts.append("실격 조건 통과: " + ", ".join(disqualifier_labels))
    if preference_labels:
        text = "선호 충족: " + ", ".join(preference_labels)
        total = member_fulfillment.get("total", 0)
        if total:
            text += f" ({member_fulfillment.get('satisfied', 0)}/{total}명)"
        parts.append(text)
    return " · ".join(parts) if parts else "반경 안 후보 중 활성 실격 조건에 걸리지 않은 곳이에요"


def select_top_candidates(
    candidates: Sequence[ScoredCandidate],
    anchor_points_by_region: Mapping[str, Sequence[tuple[float, float]]],
    *,
    limit: int = 3,
) -> list[str]:
    """3단계 — 상위 N곳(기본 3곳) 고르기(이슈 #112).

    한 번에 정렬하지 않고 점수 높은 순으로 하나씩 집는다 — 동네 배분 tie-break가 "이미 뽑힌
    동네"에 따라 달라지기 때문이다. 우선순위: 1) 점수(무조건 우선 — 동네 배분이 점수를 이기지
    않는다) 2) 점수가 같으면 아직 안 뽑힌 동네(region_label) 우선 3) 그래도 같으면 그 무리의
    기준 핀들까지 거리 "평균"(합이 아니다 — 무리마다 기준 핀 개수가 달라 합으로 비교하면
    핀이 적은 동네가 무조건 유리해진다)이 가까운 쪽.

    anchor_points_by_region에 후보의 region_label 키가 없거나 빈 시퀀스면 ValueError —
    "후보가 존재한다는 건 그 후보가 어떤 원 안에 있다는 뜻이고, 그 원의 중심이 기준 핀이다.
    0개라면 반경 계산이 깨진 것"(이슈 본문)이라 거리를 0으로 취급하고 넘어가지 않는다."""

    def avg_distance(candidate: ScoredCandidate) -> float:
        anchors = anchor_points_by_region.get(candidate.region_label) or ()
        if not anchors:
            raise ValueError(f"기준 핀이 없습니다: region_label={candidate.region_label!r}")
        distances = [
            haversine_distance_m(candidate.lat, candidate.lng, anchor_lat, anchor_lng)
            for anchor_lat, anchor_lng in anchors
        ]
        return sum(distances) / len(distances)

    remaining = list(candidates)
    chosen_ids: list[str] = []
    chosen_regions: set[str] = set()

    while remaining and len(chosen_ids) < limit:
        best = min(
            remaining,
            key=lambda c: (-c.score, c.region_label in chosen_regions, avg_distance(c)),
        )
        chosen_ids.append(best.place_id)
        chosen_regions.add(best.region_label)
        remaining.remove(best)

    return chosen_ids
