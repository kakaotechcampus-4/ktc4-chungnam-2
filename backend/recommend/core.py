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

from common.errors import AppError
from common.geo import haversine_distance_m
from recommend.models import RecommendRun
from recommend.ports import Circle
from recommend.schemas import Check

ATTEMPT_LIMIT = 5  # docs/data-model.md #31 확정: 개인 단위, 카테고리 무관, 상한 5회
# 가드레일4 "반경을 넓히는 것은 사람이 한다"는 배율 자체를 규정하지 않는다 — 2배는 이 세션의
# 판단(for_Root.md에 루트 확인 요청으로 기록).
WIDEN_FACTOR = 2.0


def check_run_ready(run: RecommendRun) -> None:
    """run.status가 'done'이 아니면 409 NOT_READY.

    done이 아닌 나머지 상태(collecting_evidence/awaiting_region_confirm/executing/failed)를
    전부 동일하게 취급한다 — mentor-review-plan.md 실패 매핑 표는 "run이 아직 완료 안 됨"
    하나로만 다뤘다. failed를 다른 코드로 구분할지는 이 계획 범위 밖의 결정이라 루트 확인이
    필요하다(for_Root.md에 기록)."""
    if run.status != "done":
        raise AppError("NOT_READY")


def required_count(member_count: int) -> int:
    """ceil(N/2) — docs/api-spec.yaml Readiness.required_count. N의 정의(#32)는 여전히
    결정 이슈 미결이라 호출부(service.py)가 넘겨주는 member_count를 그대로 따른다."""
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


def widen_radius(circle: Circle) -> Circle:
    """반경 넓히기(5-6-1, 가드레일4) — 배율은 WIDEN_FACTOR. **주의**: "사람이 명시한 원은
    자동으로 넓히지 않는다"는 가드레일4의 구분(기본값 원 vs 명시적 원)을 이 함수 자체는
    모른다 — 호출부(flows.py::widen_run)가 위젯 대상 원을 이미 골라 넘긴다는 전제다. 어떤
    원이 "기본값"인지 판별하는 규칙 자체가 현재 문서에 없어 이 세션이 임시로 좁혀 적용한
    범위는 for_Root.md에 남긴다."""
    return Circle(anchor_lat=circle.anchor_lat, anchor_lng=circle.anchor_lng, radius_m=round(circle.radius_m * WIDEN_FACTOR))


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


def apply_disqualifier_filters(candidate_checks: list[list[Check]]) -> list[bool]:
    """5-6 3단계(실격 조건) + 가드레일9("한 명이라도 실격이면 후보에서 내린다"의 조건판
    버전 — 여기서는 "체크 하나라도 불통과면 후보 전체 탈락"). 후보별 checks 리스트를 받아
    후보별 통과 여부(bool) 리스트를 그대로 반환한다 — 실제 제거는 호출부(service.py)가 이
    bool로 후보 리스트를 필터링한다(이 함수는 후보 객체 자체를 모른다 — 순수하게 checks만
    본다)."""
    return [all(check.passed for check in checks) for checks in candidate_checks]


def funnel_counts(stage_removed: list[tuple[str, int]]) -> list[dict]:
    """5-6 깔때기 표 — (라벨, 이번 단계에서 제거된 수) 쌍의 리스트를 api-spec.yaml
    FunnelEntry 모양으로 그대로 옮긴다."""
    return [{"label": label, "removed_count": removed} for label, removed in stage_removed]


def check_retry_limit(attempt_no: int) -> None:
    """재시도 상한(#31: 개인 단위, 카테고리 무관, 상한 5회). attempt_no는 다음 시도를 실행하기
    *전* 현재까지의 시도 횟수 — 이미 상한에 도달했으면(이번이 6번째가 될 것이므로) 429."""
    if attempt_no >= ATTEMPT_LIMIT:
        raise AppError("RETRY_LIMIT", detail={"attempt_no": attempt_no})
