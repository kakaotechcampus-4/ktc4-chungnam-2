"""계획 보조 에이전트의 판단 — 순수 함수만 둔다. DB를 모르고 시각은 인자로 받는다(docs/code-quality.md 기능형 코어).

- 기준 시간(명세 6.1), 탐지기 4종(6.2~6.5), 신호(Signal)와 해시(3절)
- 개입 정책(12.3), 우선순위 코드 규칙(7절, #582), 다음 점검 시각(12.4), 제안 뒤 24시간 안 확정 판정(12.9, #613)
- 우선순위 정책 파일(`priority_policy.yaml`) 로더 — 파일 읽기 한 곳만 I/O다
- 코드 유형 템플릿(6.4, 6.5)과 렌더(11절 끝 "저장과 렌더 시점"), 이벤트 페이로드(15절) — #531
- 진단 입력(12.4 6단계), 충돌 종류(6.3), 모델 출력 검증(11.2) — #533
- 우리 조건 요약(8절): 갱신 판단, 다섯 칸 나누기, 고정 문구 렌더 — #586
- 추천 막힘 조언(9절): 대상 판정, 도구 결과 모양, 출력 검증, 렌더 — #587

입력은 `agent.snapshot.Snapshot`(관찰 한 번의 사본)과 `History`(이 지도의 제안 이력, #515가 채운다)다.
Signal과 features에는 사유 글을 넣지 않는다 — 근거는 reaction_id와 pin_id로만 가리킨다(명세 2절 13번).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from statistics import median
from typing import TYPE_CHECKING, Any

import yaml

from agent.constants import (
    BACKOFF_HOURS,
    BLOCKED_RUN_MAX_RESULTS,
    BLOCKED_RUN_MIN_SAME_CATEGORY_RUNS,
    CATEGORY_GAP_MIN_CONFIRMED,
    CODE_TYPES,
    DDAY_FACTOR_FAR,
    DDAY_FACTOR_MID,
    DDAY_FACTOR_NEAR,
    DDAY_FAR,
    DDAY_MID,
    DECIDED_WINDOW,
    MODEL_TYPES,
    NO_REACTION_DAILY_LIMIT,
    NOT_FILTERED_CHIP_IDS,
    NO_REACTION_MIN_TARGET_PINS,
    NO_REACTION_UNSEEN_RATIO,
    PER_MEMBER_DAILY_MODEL_USES,
    RHYTHM_DEFAULT_BASE,
    RHYTHM_MIN_EVENTS,
    RHYTHM_WINDOW_EVENTS,
    SAFETY_WORDS,
    SHADOW_DIAGNOSES,
    STALL_ACTIVE_MEMBERS,
    SUMMARY_NEW_REASONS,
    TIME_MAX,
    TIME_MIN,
    TIME_MULTIPLIER,
)
from agent.schemas import (
    AgentAction,
    AgentAdviceLine,
    AgentAnalysis,
    AgentConflictAxis,
    AgentNotFiltered,
    AgentSettings,
    AgentSplitPref,
    AgentState,
    AgentSuggestion,
    AgentSummary,
    AgentSummaryItem,
    AgentUsage,
    AgentVagueFixable,
    CountClaim,
    DiagnosisOutput,
    QuoteClaim,
    RefClaim,
    RunAdvice,
    RunAdviceOutput,
    ToolClaim,
)
from common import categories
from common.events import Event

if TYPE_CHECKING:
    from agent.snapshot import Reaction, Snapshot

DIAGNOSES = MODEL_TYPES + CODE_TYPES

# constants.DAY_BOUNDARY_TZ("Asia/Seoul")의 고정 오프셋. 한국은 서머타임이 없어(1988년 이후) +9시간과 같다.
# zoneinfo는 Windows에서 tzdata 패키지가 있어야 해서 쓰지 않는다.
KST = timezone(timedelta(hours=9), "KST")


def kst_date(now: datetime) -> date:
    if now.tzinfo is None:
        raise ValueError("now는 timezone-aware여야 합니다 — naive datetime은 KST/UTC 혼동을 부른다")
    return now.astimezone(KST).date()


def kst_day_start(now: datetime) -> datetime:
    """now가 속한 KST 하루의 시작(자정). 모델 사용 상한과 no_reaction 하루 1회의 경계다."""
    d = kst_date(now)
    return datetime(d.year, d.month, d.day, tzinfo=KST)


# ---------------------------------------------------------------- 기준 시간 (6.1)

def rhythm_base(action_times: Sequence[datetime]) -> timedelta:
    """최근 행동 20개 간격의 중앙값 × 배수. 6개 미만이면 기본값(배수를 곱하지 않는다)."""
    recent = sorted(action_times)[-RHYTHM_WINDOW_EVENTS:]
    if len(recent) < RHYTHM_MIN_EVENTS:
        return RHYTHM_DEFAULT_BASE
    gaps = [b - a for a, b in zip(recent, recent[1:])]
    return median(gaps) * TIME_MULTIPLIER


def dday_factor(start_date: date, today: date) -> float:
    d = (start_date - today).days   # 여행 중이면 0 이하
    if d >= DDAY_FAR:
        return DDAY_FACTOR_FAR
    if d >= DDAY_MID:
        return DDAY_FACTOR_MID
    return DDAY_FACTOR_NEAR


def time_threshold(action_times: Sequence[datetime], start_date: date, today: date) -> timedelta:
    raw = rhythm_base(action_times) * dday_factor(start_date, today)
    return min(max(raw, TIME_MIN), TIME_MAX)


# ---------------------------------------------------------------- 신호 (3절, 6절)

# 근거 하나: (id, 종류, 시각). 반응이면 (reaction_id, like|against, updated_at), 핀이면 (pin_id, pin, created_at),
# 확정 항목이면 (pin_id, confirmed, added_at). evidence_hash가 이 셋을 본다.
Evidence = tuple[str, str, datetime]


@dataclass(frozen=True)
class Signal:
    id: str                          # 관찰 안에서의 식별자 s1, s2 … (detect_all이 매긴다)
    diagnosis: str                   # stall | split | no_reaction | category_gap
    category: str | None
    pin_id: str | None               # split만
    evidence_ids: tuple[str, ...]    # 정렬된 reaction_id 또는 pin_id
    features: Mapping[str, Any]      # 우선순위 입력(7절). 사유 글은 넣지 않는다
    fingerprint: str
    evidence_hash: str


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _utc_iso(at: datetime) -> str:
    return at.astimezone(timezone.utc).isoformat()


def fingerprint(diagnosis: str, category: str | None, evidence_ids: Iterable[str]) -> str:
    """중복 금지용 — 유형 + 카테고리 + 정렬된 근거 id."""
    return _digest([diagnosis, category, sorted(evidence_ids)])


def evidence_hash(evidence: Iterable[Evidence]) -> str:
    """상태 재확인용 — 근거 id + 종류(반응이면 like/against) + 시각. 같은 시각은 UTC로 맞춰 비교한다."""
    return _digest(sorted([eid, kind, _utc_iso(at)] for eid, kind, at in evidence))


def make_signal(
    diagnosis: str, *, category: str | None, evidence: Sequence[Evidence], features: Mapping[str, Any],
    pin_id: str | None = None,
) -> Signal:
    ids = tuple(sorted({eid for eid, _, _ in evidence}))
    return Signal(
        id="", diagnosis=diagnosis, category=category, pin_id=pin_id, evidence_ids=ids, features=dict(features),
        fingerprint=fingerprint(diagnosis, category, ids), evidence_hash=evidence_hash(evidence),
    )


def _features(
    s: Snapshot, *, category: str | None, affected: int, elapsed_ratio: float | None, trigger: str | None,
) -> dict[str, Any]:
    """recent_dismissals는 이력을 봐야 해서 check_policy가 통과한 신호에 채운다. 탐지 시점에는 0이다."""
    return {
        "affected_members": affected,
        "elapsed_ratio": elapsed_ratio,
        "dday": (s.map.start_date - s.today).days,
        "recent_dismissals": 0,
        "trigger": trigger,
        "category": category,
    }


def _reaction_evidence(reactions: Iterable[Reaction]) -> list[Evidence]:
    return [(r.reaction_id, r.type, r.updated_at) for r in reactions]


# ---------------------------------------------------------------- 탐지기 (6.2~6.5)

def _stall_candidates(s: Snapshot) -> list[tuple[str, list[Reaction], datetime]]:
    """공통 전제를 만족한 (카테고리, 🚫 반응들, t0). t0 = 그 카테고리 🚫 중 가장 늦은 updated_at.
    전제: t0 뒤에 그 카테고리 핀이 새로 없고, run이 없고(bool만), 그 카테고리 확정이 없다."""
    out = []
    for c in categories.pinnable():
        againsts = [r for r in s.reactions if r.type == "against" and s.pin(r.pin_id).category == c]
        if not againsts:
            continue
        t0 = max(r.updated_at for r in againsts)
        if any(p.category == c and p.created_at > t0 for p in s.pins):
            continue
        if s.has_run_since(c, t0):
            continue
        if any(s.pin(i.pin_id).category == c for i in s.shortlist):
            continue
        out.append((c, againsts, t0))
    return out


def detect_stall(s: Snapshot, now: datetime, th: timedelta) -> list[Signal]:
    """반대 후 정체(6.2). 공통 전제 + (다른 카테고리에서 t0 뒤 활동한 사람 2명 이상 또는 t0부터 기준 시간 경과)."""
    out = []
    for c, againsts, t0 in _stall_candidates(s):
        actors = {a.user_id for a in s.actions if a.at > t0 and a.category != c}
        by_activity = len(actors) >= STALL_ACTIVE_MEMBERS
        by_time = now - t0 >= th
        if not (by_activity or by_time):
            continue
        out.append(make_signal(
            "stall", category=c, evidence=_reaction_evidence(againsts),
            features=_features(
                s, category=c, affected=len({r.user_id for r in againsts}), elapsed_ratio=(now - t0) / th,
                trigger="activity" if by_activity else "time",
            ),
        ))
    return out


def _split_counts(s: Snapshot, pin_id: str) -> tuple[list[Reaction], bool]:
    """(그 핀의 반응, 갈림 모양인가). 갈림 모양 = ♥ 1 이상, 🚫 1 이상, ♥ ≥ 🚫(#360)."""
    rs = s.reactions_of(pin_id)
    like = sum(r.type == "like" for r in rs)
    against = sum(r.type == "against" for r in rs)
    return rs, like >= 1 and against >= 1 and like >= against


def detect_split(s: Snapshot, now: datetime, th: timedelta) -> list[Signal]:
    """의견 갈림(6.3). 확정되지 않은 핀에서 갈림 모양이고, 구성원 전원이 반응했거나 마지막 반응부터 기준 시간 경과.
    충돌 종류(compare_reasons)는 ②의 키와 방향이 있어야 해서 M1 도구와 함께 만든다."""
    out = []
    for p in s.pins:
        if s.is_confirmed(p.pin_id):
            continue
        rs, split_shape = _split_counts(s, p.pin_id)
        if not split_shape:
            continue
        last = max(r.updated_at for r in rs)
        if len(rs) == s.member_count:
            trigger = "all_responded"
        elif now - last >= th:
            trigger = "time"
        else:
            continue
        out.append(make_signal(
            "split", category=p.category, pin_id=p.pin_id, evidence=_reaction_evidence(rs),
            features=_features(
                s, category=p.category, affected=len({r.user_id for r in rs}), elapsed_ratio=(now - last) / th,
                trigger=trigger,
            ),
        ))
    return out


def detect_no_reaction(s: Snapshot, now: datetime, th: timedelta) -> list[Signal]:
    """반응 공백(6.4). 구성원마다 대상 핀(남이 찍었고 max(핀 생성, 내 합류)부터 기준 시간 경과)이 3개 이상이고 그중
    절반 이상에 반응이 없으면 그 핀들을 모은다. 누가 확인하지 않았는지는 신호에 담지 않는다(수만 센다)."""
    unseen_all: dict[str, datetime] = {}
    affected = 0
    for m in s.members:
        targets = [p for p in s.pins if p.created_by != m.user_id and now - max(p.created_at, m.joined_at) >= th]
        if len(targets) < NO_REACTION_MIN_TARGET_PINS:
            continue
        unseen = [p for p in targets if not s.has_reaction(m.user_id, p.pin_id)]
        if len(unseen) / len(targets) >= NO_REACTION_UNSEEN_RATIO:
            affected += 1
            unseen_all |= {p.pin_id: p.created_at for p in unseen}
    if not unseen_all:
        return []
    return [make_signal(
        "no_reaction", category=None, evidence=[(pid, "pin", at) for pid, at in unseen_all.items()],
        features=_features(s, category=None, affected=affected, elapsed_ratio=None, trigger=None),
    )]


def detect_category_gap(s: Snapshot) -> list[Signal]:
    """카테고리 공백(6.5). 확정이 2곳 이상인데 관찰 대상 카테고리 중 확정이 없는 곳. 숙소와 기타는 핀을 만들 수
    없어(pinnable 아님) 보지 않는다."""
    if len(s.shortlist) < CATEGORY_GAP_MIN_CONFIRMED:
        return []
    confirmed = [(i.pin_id, "confirmed", i.added_at) for i in s.shortlist]
    out = []
    for c in categories.pinnable():
        if c == "숙소" and s.map.end_date == s.map.start_date:
            continue   # 숙소가 다시 핀이 되면(v2): 당일치기는 숙소 공백을 보지 않는다
        if any(s.pin(i.pin_id).category == c for i in s.shortlist):
            continue
        out.append(make_signal(
            "category_gap", category=c, evidence=confirmed,
            features=_features(s, category=c, affected=s.member_count, elapsed_ratio=None, trigger=None),
        ))
    return out


def detect_all(s: Snapshot, now: datetime, th: timedelta) -> list[Signal]:
    """네 탐지기를 차례로 돌리고 관찰 안의 id(s1, s2 …)를 매긴다."""
    found = (
        detect_stall(s, now, th) + detect_split(s, now, th) + detect_no_reaction(s, now, th) + detect_category_gap(s)
    )
    return [replace(sig, id=f"s{i}") for i, sig in enumerate(found, start=1)]


# ---------------------------------------------------------------- 정책 (12.3)

@dataclass(frozen=True)
class PastSuggestion:
    """이 지도의 지난 제안 한 건(agent_suggestions 한 행에서 정책이 보는 칸만). #515 service.load_history가 채운다."""
    id: str
    diagnosis: str
    category: str | None
    fingerprint: str
    status: str                      # active | accepted | dismissed | expired | superseded
    created_at: datetime
    resolved_at: datetime | None = None
    expires_at: datetime | None = None
    evidence_hash: str | None = None   # 활성 제안의 무효화 판단(find_superseded)에 쓴다


@dataclass(frozen=True)
class SummaryMeta:
    """이 지도의 카테고리 요약 한 건에서 갱신 판단(8절)이 보는 것 — 요약을 만들 때 본 사유 있는 반응 id와 갱신 시각."""
    category: str
    reaction_ids: frozenset[str]
    updated_at: datetime


@dataclass(frozen=True)
class History:
    suggestions: tuple[PastSuggestion, ...] = ()   # 이 지도, 최신순(created_at 내림차순)
    model_runs_today: int = 0   # KST 자정 이후 used_model=true(진단을 부름)이고 trigger in (activity, time, summary)인 agent_runs 수
    summaries: tuple[SummaryMeta, ...] = ()   # 이 지도의 카테고리 요약(#586)

    @property
    def active(self) -> PastSuggestion | None:
        return next((h for h in self.suggestions if h.status == "active"), None)


@dataclass(frozen=True)
class Blocked:
    signal_id: str
    reason: str   # active_exists | duplicate | backoff | daily_limit | model_cap | mode_off(저장 직전 모드가 꺼짐, #531)


CLOSED_BY_PEOPLE = ("accepted", "dismissed", "expired")   # superseded는 사람이 내린 판단이 아니라 다시 낼 수 있다


def dismissal_streak(
    history: Sequence[PastSuggestion], diagnosis: str, category: str | None,
) -> tuple[int, datetime | None]:
    """같은 유형·카테고리의 연속 닫힘 수와 가장 최근 닫힘 시각. 수락하면 끊기고, 만료와 무효화는 세지 않는다."""
    streak, last_dismissed_at = 0, None
    for sug in history:   # 최신순
        if (sug.diagnosis, sug.category) != (diagnosis, category):
            continue
        if sug.status == "accepted":
            break
        if sug.status == "dismissed":
            streak += 1
            last_dismissed_at = last_dismissed_at or sug.resolved_at
    return streak, last_dismissed_at


def backoff_until(history: Sequence[PastSuggestion], diagnosis: str, category: str | None) -> datetime | None:
    """연속 닫힘 1회 2시간, 2회 6시간, 3회 이상 24시간. 닫힘이 없으면 None."""
    streak, last_dismissed_at = dismissal_streak(history, diagnosis, category)
    if streak == 0 or last_dismissed_at is None:
        return None
    hours = BACKOFF_HOURS[min(streak, len(BACKOFF_HOURS)) - 1]
    return last_dismissed_at + timedelta(hours=hours)


def model_cap_reached(runs_today: int, member_count: int) -> bool:
    """지도 상한 = 구성원 수 × 4(하루, KST 자정 초기화). runs_today는 History.model_runs_today."""
    return runs_today >= member_count * PER_MEMBER_DAILY_MODEL_USES


def check_policy(
    signals: Sequence[Signal], history: History, snapshot: Snapshot, now: datetime,
    *, superseding: Iterable[str] = (),
) -> tuple[list[Signal], list[Blocked]]:
    """모델 호출 전 신호 거르기(12.3). (통과한 신호, 막힌 신호와 이유).

    순서: 1 활성 제안(이번 관찰에서 무효화될 것은 빼고) → 2 fingerprint 중복 → 3 백오프 → 4 no_reaction 하루 1회
    → 5 모델 사용 상한(모델 유형만, 코드 유형은 통과). 신호 하나는 처음 걸린 이유 하나로만 막힌다.
    통과한 신호의 features에 recent_dismissals를 채운다."""
    active = history.active
    if active is not None and active.id not in set(superseding):
        return [], [Blocked(sig.id, "active_exists") for sig in signals]

    closed = {h.fingerprint for h in history.suggestions if h.status in CLOSED_BY_PEOPLE}
    day_start = kst_day_start(now)
    no_reaction_today = sum(h.diagnosis == "no_reaction" and h.created_at >= day_start for h in history.suggestions)
    cap = model_cap_reached(history.model_runs_today, snapshot.member_count)

    passed, blocked = [], []
    for sig in signals:
        until = backoff_until(history.suggestions, sig.diagnosis, sig.category)
        if sig.fingerprint in closed:
            blocked.append(Blocked(sig.id, "duplicate"))
        elif until is not None and now < until:
            blocked.append(Blocked(sig.id, "backoff"))
        elif sig.diagnosis == "no_reaction" and no_reaction_today >= NO_REACTION_DAILY_LIMIT:
            blocked.append(Blocked(sig.id, "daily_limit"))
        elif cap and sig.diagnosis in MODEL_TYPES:
            blocked.append(Blocked(sig.id, "model_cap"))
        else:
            streak, _ = dismissal_streak(history.suggestions, sig.diagnosis, sig.category)
            passed.append(replace(sig, features={**sig.features, "recent_dismissals": streak}))
    return passed, blocked


# ---------------------------------------------------------------- 우선순위 정책과 코드 규칙 (7절)

POLICY_PATH = Path(__file__).with_name("priority_policy.yaml")


@dataclass(frozen=True)
class PriorityPolicy:
    version: int
    urgent_dday: int
    never_first: tuple[str, ...]
    always_first: tuple[str, ...]
    weights: Mapping[str, int]


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def parse_policy(raw: Mapping[str, Any]) -> PriorityPolicy:
    """weights에 diagnosis 4종이 모두 있어야 하고, rules에는 정수 urgent_dday와 아는 diagnosis만 올 수 있다. 어긋나면
    ValueError."""
    weights = dict(raw.get("weights") or {})
    if set(weights) != set(DIAGNOSES):
        raise ValueError(f"priority_policy weights는 {sorted(DIAGNOSES)}를 모두 가져야 한다: {sorted(weights)}")
    if not all(_is_int(w) for w in weights.values()):
        raise ValueError(f"priority_policy weights는 정수여야 한다: {weights}")
    rules = raw.get("rules") or {}
    urgent_dday = rules.get("urgent_dday")
    if not _is_int(urgent_dday):
        raise ValueError(f"priority_policy rules.urgent_dday는 정수여야 한다: {urgent_dday!r}")
    never_first = tuple(rules.get("never_first") or ())
    always_first = tuple(rules.get("always_first") or ())
    unknown = set(never_first + always_first) - set(DIAGNOSES)
    if unknown:
        raise ValueError(f"priority_policy rules에 모르는 diagnosis: {sorted(unknown)}")
    return PriorityPolicy(
        version=int(raw["version"]), urgent_dday=urgent_dday,
        never_first=never_first, always_first=always_first, weights=weights,
    )


@lru_cache(maxsize=1)
def load_policy(path: Path = POLICY_PATH) -> PriorityPolicy:
    with open(path, encoding="utf-8") as f:
        return parse_policy(yaml.safe_load(f))


def rank_signals(signals: Sequence[Signal], policy: PriorityPolicy) -> tuple[list[Signal], list[str]]:
    """코드 규칙으로 정한 순위와 기본 순서를 바꾼 규칙 이름들(7절, #582). 기본 순서는 weights 내림차순(같으면 탐지
    순서)이고, 아래 규칙을 차례로 얹어 순서가 바뀐 규칙만 rule_hits에 남긴다(바뀐 차례대로).

    - 같은 weight 안에서: recent_dismissals가 0인 신호 먼저(recent_dismissals) → affected_members 내림차순
      (affected_members) → elapsed_ratio 내림차순, 없으면 뒤(elapsed_ratio). 앞 기준이 같을 때만 다음 기준을 본다
    - urgent_dday: 출발이 urgent_dday일 이내(여행 중 포함)면 category_gap을 맨 앞으로
    - always_first: 그 유형을 맨 앞으로. never_first: 1순위가 그 유형이면 아닌 첫 신호를 앞으로

    결과는 7절의 순서(urgent_dday → weights → 같은 weight의 기준 → always_first, never_first)와 같다 — 맨 앞으로
    옮기기는 안정 정렬이라 옮긴 신호끼리도, 남은 신호끼리도 앞 단계의 순서를 지킨다."""
    def weight(s: Signal) -> int:
        return -policy.weights[s.diagnosis]

    def dismissed(s: Signal) -> bool:
        return (s.features.get("recent_dismissals") or 0) > 0

    def affected(s: Signal) -> int:
        return -(s.features.get("affected_members") or 0)

    def elapsed(s: Signal) -> tuple[bool, float]:
        ratio = s.features.get("elapsed_ratio")
        return ratio is None, -(ratio or 0.0)

    def urgent_gap(s: Signal) -> bool:
        dday = s.features.get("dday")
        return s.diagnosis == "category_gap" and dday is not None and dday <= policy.urgent_dday

    order, hits = sorted(signals, key=weight), []

    def step(rule: str, new_order: list[Signal]) -> None:
        nonlocal order
        if new_order != order:
            hits.append(rule)
        order = new_order

    keys = [weight]
    for rule, key in (("recent_dismissals", dismissed), ("affected_members", affected), ("elapsed_ratio", elapsed)):
        keys.append(key)
        step(rule, sorted(order, key=lambda s, ks=tuple(keys): tuple(k(s) for k in ks)))
    step("urgent_dday", sorted(order, key=lambda s: not urgent_gap(s)))
    step("always_first", sorted(order, key=lambda s: s.diagnosis not in policy.always_first))
    if order and order[0].diagnosis in policy.never_first:
        allowed = next((s for s in order if s.diagnosis not in policy.never_first), None)
        if allowed is not None:
            step("never_first", [allowed] + [s for s in order if s is not allowed])
    return order, hits


def fallback_order(signals: Sequence[Signal], policy: PriorityPolicy) -> list[Signal]:
    """코드 규칙으로 정한 순위(7절). 규칙은 rank_signals."""
    return rank_signals(signals, policy)[0]


# ---------------------------------------------------------------- 다음 점검 시각 (12.4)

def next_check_at(snap: Snapshot, history: History, now: datetime, th: timedelta) -> datetime | None:
    """시간 기준이 가장 먼저 만료될 미래 시각. 후보: 전제를 만족한 정체 카테고리의 t0 + th, 갈림 모양인 핀의
    마지막 반응 + th, 반응 공백 대상이 될 핀(구성원이 아직 반응하지 않은 남의 핀)이 기준 시간에 닿는 시각, 활성 제안의
    expires_at. 이미 지난 시각은 빼고(지금 신호로 이미 잡힌다), 후보가 없으면 None."""
    candidates = [t0 + th for _, _, t0 in _stall_candidates(snap)]
    for p in snap.pins:
        if snap.is_confirmed(p.pin_id):
            continue
        rs, split_shape = _split_counts(snap, p.pin_id)
        if split_shape and len(rs) < snap.member_count:
            candidates.append(max(r.updated_at for r in rs) + th)
    for m in snap.members:
        candidates += [
            max(p.created_at, m.joined_at) + th
            for p in snap.pins
            if p.created_by != m.user_id and not snap.has_reaction(m.user_id, p.pin_id)
        ]
    active = history.active
    if active is not None and active.expires_at is not None:
        candidates.append(active.expires_at)
    future = [t for t in candidates if t > now]
    return min(future) if future else None


# ---------------------------------------------------------------- 관찰 흐름의 판단 (12.4, 12.5, 12.8)

RECENT_EVENT_GRACE = timedelta(seconds=2)   # realtime/core.py GRACE와 같은 값


def has_recent_event(latest_event_at: datetime | None, now: datetime) -> bool:
    """가장 최근 이벤트가 2초 안이면 True — 그보다 작은 seq가 늦게 커밋될 수 있어 다음 tick에 한 번 더 본다(12.5)."""
    return latest_event_at is not None and now - latest_event_at < RECENT_EVENT_GRACE


def find_superseded(active: PastSuggestion | None, signals: Sequence[Signal]) -> list[str]:
    """활성 제안을 무효화할지(12.9). 같은 fingerprint의 신호가 사라졌거나 evidence_hash가 바뀌었으면 그 id 하나."""
    if active is None:
        return []
    if any(s.fingerprint == active.fingerprint and s.evidence_hash == active.evidence_hash for s in signals):
        return []
    return [active.id]


def recheck(signal: Signal, snap: Snapshot, now: datetime, th: timedelta) -> bool:
    """상태 재확인(12.8). 저장 직전에 다시 읽은 사본으로 같은 탐지기를 돌려, 같은 fingerprint와 evidence_hash의
    신호가 아직 있으면 True. seq를 비교하지 않는다(커밋 순서 구멍과 무관하게 실제 값을 본다)."""
    return any(
        s.fingerprint == signal.fingerprint and s.evidence_hash == signal.evidence_hash
        for s in detect_all(snap, now, th)
    )


def model_usage(usages: Sequence[AgentUsage]) -> dict[str, Any]:
    """agent_runs의 model, prompt_version, tokens_in, tokens_out(#564). 관찰에서 모델을 부르는 곳은 진단 하나다(우선순위는
    코드 규칙, #582). 여러 호출이 오면 토큰은 더하고, 모델과 프롬프트 버전은 겹치지 않게 부른 순서대로 "+"로 잇는다.
    아무것도 부르지 않았거나 고정 응답 스텁이면 None과 0이다."""
    def joined(values: Iterable[str | None]) -> str | None:
        return "+".join(dict.fromkeys(v for v in values if v)) or None

    return {
        "model": joined(u.model for u in usages),
        "prompt_version": joined(u.prompt_version for u in usages),
        "tokens_in": sum(u.tokens_in for u in usages),
        "tokens_out": sum(u.tokens_out for u in usages),
    }


def choose_top(passed: Sequence[Signal], policy: PriorityPolicy) -> tuple[Signal | None, dict[str, Any] | None]:
    """1순위 신호와 agent_runs.priority 기록(7절, #582). 순위는 코드 규칙(rank_signals)만 쓴다 — 모델을 부르지 않는다.

    기록: source(single: 신호 하나, rules: 2개 이상을 규칙으로 정함), final_order, fingerprints(final_order 순서),
    rule_hits(기본 순서를 바꾼 규칙). 사유 글은 없다."""
    if not passed:
        return None, None
    order, rule_hits = rank_signals(passed, policy)
    log = {
        "source": "single" if len(passed) == 1 else "rules", "final_order": [s.id for s in order],
        "fingerprints": [s.fingerprint for s in order], "rule_hits": rule_hits,
    }
    return order[0], log


def signal_record(sig: Signal) -> dict[str, Any]:
    """agent_runs.signals 한 칸. 근거는 id로만 담고 사유 글은 없다(명세 2절 13번)."""
    return {
        "id": sig.id, "diagnosis": sig.diagnosis, "category": sig.category, "pin_id": sig.pin_id,
        "evidence_ids": list(sig.evidence_ids), "features": dict(sig.features),
        "fingerprint": sig.fingerprint, "evidence_hash": sig.evidence_hash,
    }


# ---------------------------------------------------------------- 제안 뒤 24시간 안 확정 (12.9, #613)

CATEGORY_DECIDED = ("category_gap", "stall")   # 제안 카테고리의 핀이 확정되면 참. 나머지는 가리킨 핀으로 본다


@dataclass(frozen=True)
class Confirmation:
    """확정 항목 하나. category는 핀의 지금 분류(#466) — 분류를 읽지 못한 핀(삭제된 핀 등)은 None."""
    pin_id: str
    category: str | None
    added_at: datetime


@dataclass(frozen=True)
class DecisionTarget:
    """decided_within_24h를 채울 제안 — agent_suggestions에서 판정에 쓰는 칸만."""
    id: Any
    diagnosis: str
    category: str | None
    pin_id: str | None
    claims: Sequence[Mapping[str, Any]]
    actions: Sequence[Mapping[str, Any]]
    created_at: datetime


def pointed_pin_ids(target: DecisionTarget) -> frozenset[str]:
    """제안이 가리킨 핀. split은 pin_id, no_reaction은 핀 ref claim과 show_pins 버튼의 pin_ids(근거 id 그대로, 6.4)."""
    if target.diagnosis == "split":
        return frozenset([target.pin_id] if target.pin_id else [])
    shown = (pid for a in target.actions if a.get("type") == "show_pins" for pid in a.get("params", {}).get("pin_ids", []))
    return frozenset(referenced_pin_ids(target.claims)) | frozenset(shown)


def decided_within_24h(target: DecisionTarget, confirmations: Iterable[Confirmation]) -> bool:
    """제안 created_at부터 DECIDED_WINDOW(24시간) 안에(양 끝 포함) 확정된 항목이 있는가. category_gap과 stall은 제안
    카테고리의 핀, split과 no_reaction은 제안이 가리킨 핀이 확정됐는지 본다. 확정 항목은 지금 남은 것이라 삭제된 핀의
    항목도 들어오면 센다(분류를 모르면 카테고리 유형에서는 세지 못한다)."""
    end = target.created_at + DECIDED_WINDOW
    in_window = [c for c in confirmations if target.created_at <= c.added_at <= end]
    if target.diagnosis in CATEGORY_DECIDED:
        return target.category is not None and any(c.category == target.category for c in in_window)
    if target.diagnosis in ("split", "no_reaction"):
        pins = pointed_pin_ids(target)
        return any(c.pin_id in pins for c in in_window)
    raise ValueError(f"알 수 없는 diagnosis: {target.diagnosis}")


# ---------------------------------------------------------------- 노출 (#531)

def is_shadow(diagnosis: str) -> bool:
    """이 유형의 제안을 저장만 하고 화면과 이벤트로 내보내지 않는가(constants.SHADOW_DIAGNOSES)."""
    return diagnosis in SHADOW_DIAGNOSES


# ---------------------------------------------------------------- 코드 유형 템플릿 (6.4, 6.5)

@dataclass(frozen=True)
class Draft:
    """저장할 제안 초안 — agent_suggestions의 title, claims, advice, actions 칸 그대로(명세 11절 끝, 13절).

    title과 advice는 슬롯 문장이다. `{cN.value}`는 count claim의 값, `{cN}`은 핀 ref면 핀 이름, quote면 그 반응의
    지금 사유 글로 렌더 때 채운다. 핀 이름과 사유 글은 저장하지 않는다(명세 2절 13번). actions의 label과 params에는
    슬롯이 없다(카테고리 이름과 id뿐)."""
    title: str
    claims: list[dict[str, Any]]
    advice: list[dict[str, Any]]    # [{slot_text, is_guess}]
    actions: list[dict[str, Any]]   # [{index, type, label, params}] — AgentAction 직렬화
    analysis: dict[str, Any] | None = None   # split: compare_reasons 결과(키와 reaction_id만, 사유 글 없음)


def _subject_particle(word: str) -> str:
    """주격 조사 — 마지막 글자에 받침이 있으면 '이', 없으면 '가'(음식점이, 카페가, 관광지가)."""
    last = word[-1] if word else ""
    if "가" <= last <= "힣" and (ord(last) - ord("가")) % 28:
        return "이"
    return "가"


def _actions(*specs: tuple[str, str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        AgentAction(index=i, type=type_, label=label, params=params).model_dump(mode="json")
        for i, (type_, label, params) in enumerate(specs)
    ]


def _no_reaction_draft(sig: Signal) -> Draft:
    """반응 공백(6.4). 제목 "아직 확인되지 않은 핀이 {n}개 있어요", 확인된 것은 핀 이름 한 줄씩, 버튼 "미확인 핀 보기".
    누가 확인하지 않았는지는 쓰지 않는다. 핀 이름은 ref claim으로 가리키고 렌더 때 정한다."""
    pin_ids = list(sig.evidence_ids)
    refs = [RefClaim(id=f"c{i}", kind="ref", object="pin", ref_id=pid) for i, pid in enumerate(pin_ids, start=2)]
    count = CountClaim(id="c1", kind="count", subject="map", subject_id=None, metric="unseen", value=len(pin_ids))
    return Draft(
        title="아직 확인되지 않은 핀이 {c1.value}개 있어요",
        claims=[c.model_dump() for c in (count, *refs)],
        advice=[{"slot_text": f"{{{r.id}}}", "is_guess": False} for r in refs],
        actions=_actions(("show_pins", "미확인 핀 보기", {"pin_ids": pin_ids})),
    )


def _category_gap_draft(sig: Signal) -> Draft:
    """카테고리 공백(6.5). 제목 "확정 리스트에 {category}가 아직 없어요", 확인된 것 "확정 {n}곳 중 {category} 0곳".
    버튼은 추천 대상이면 추천 받기와 핀 보기, 아니면 검색과 핀 보기(숙소가 다시 핀이 될 때 쓴다)."""
    c = sig.category
    confirmed = CountClaim(id="c1", kind="count", subject="map", subject_id=None, metric="confirmed",
                           value=len(sig.evidence_ids))
    in_category = CountClaim(id="c2", kind="count", subject="category", subject_id=c, metric="confirmed", value=0)
    first = ("open_recommend", f"{c} 추천 받기") if c in categories.recommendable() else ("search_place", f"{c} 검색")
    return Draft(
        title=f"확정 리스트에 {c}{_subject_particle(c)} 아직 없어요",
        claims=[confirmed.model_dump(), in_category.model_dump()],
        advice=[{"slot_text": f"확정 {{c1.value}}곳 중 {c} {{c2.value}}곳", "is_guess": False}],
        actions=_actions((*first, {"category": c}), ("show_pins", f"{c} 핀 보기", {"category": c})),
    )


_TEMPLATES = {"no_reaction": _no_reaction_draft, "category_gap": _category_gap_draft}


def render_template(sig: Signal) -> Draft:
    """코드 유형 신호의 초안. 신호만으로 정해진다(개수는 근거 id 수, 이름은 렌더 때). 모델 유형은 ValueError."""
    if sig.diagnosis not in _TEMPLATES:
        raise ValueError(f"{sig.diagnosis}는 템플릿 유형이 아니다 — 모델 유형은 진단(M1-2)이 초안을 만든다")
    return _TEMPLATES[sig.diagnosis](sig)


# ---------------------------------------------------------------- 모델 진단 입력 (6.2, 6.3, 10절)

def diagnosis_input(top: Signal, snap: Snapshot, comparison: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """llm.agent_diagnose에 넘길 1순위 신호. 모델에는 JSON 문자열로 그대로 간다 — 공개 데이터만 넣는다(명세 2절 2번).
    run의 존재(has_run_since)와 구성원 user_id는 넣지 않는다. 사유 글도 넣지 않는다(모델이 get_reasons로 읽는다).
    stall은 카테고리와 🚫 반응 id, 🚫가 달린 핀 id. split은 핀 id, place_id(실시간 핀은 None), 반응 id, 그 핀의 ♥·🚫
    수(counts — split 필수 claim의 값), compare_reasons 결과(충돌 종류는 코드가 정한다, 6.3). 핀 id와 수, place_id를
    넣는 것은 모델이 그것을 알려고 도구를 한 번 더 부르지 않게 하려는 것이다(#534)."""
    f = top.features
    out: dict[str, Any] = {
        "signal_id": top.id, "diagnosis": top.diagnosis, "category": top.category,
        "trigger": f.get("trigger"), "affected_members": f.get("affected_members"), "dday": f.get("dday"),
        "elapsed_ratio": f.get("elapsed_ratio"), "recent_dismissals": f.get("recent_dismissals"),
        "member_count": snap.member_count,
    }
    if top.diagnosis == "stall":
        out["against_reaction_ids"] = list(top.evidence_ids)
        out["against_pin_ids"] = sorted({r.pin_id for r in snap.reactions if r.reaction_id in set(top.evidence_ids)})
    elif top.diagnosis == "split":
        pin = snap.pin(top.pin_id)
        reactions = snap.reactions_of(top.pin_id)
        out["pin_id"] = top.pin_id
        out["place_id"] = pin.place_id if pin is not None else None
        out["reaction_ids"] = list(top.evidence_ids)
        out["counts"] = {t: sum(r.type == t for r in reactions) for t in ("like", "against")}
        out["comparison"] = comparison
    return out


# ---------------------------------------------------------------- 충돌 종류 (6.3)

def compare_reasons(reasons: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """♥ 쪽과 🚫 쪽 사유를 키별로 모으고 충돌 종류를 정한다(6.3). 입력은 structure_reasons 모양
    `[{reaction_id, type, lines: [{fact_key, wants, badge}]}]`(키와 방향은 ②와 칩 표가 정한 것).

    - keys: `[{fact_key, want: [{reaction_id, side}], avoid: [...]}]` — wants=true면 want, false면 avoid, null이면 어느
      쪽에도 넣지 않는다. side는 like(♥) 또는 against(🚫)
    - conflict_type
      - unclear: 한쪽이라도 키 있는 사유가 없다
      - same_axis: 같은 키를 두고 ♥ 쪽과 🚫 쪽 방향이 반대다(♥ quiet 원함 / 🚫 quiet 피함)
      - different_axes: 양쪽 키가 겹치지 않는다
      - 그 밖(같은 키인데 방향이 같거나 모름. 예: ♥ "조용해서 좋아요"와 🚫 칩 「시끄러워요」는 둘 다 quiet 원함이다 —
        취향이 아니라 이 가게가 조용한지를 두고 갈렸다)은 6.3 표에 없어 unclear로 둔다(for_Root.md #533)"""
    sides: dict[str, dict[str, set[bool | None]]] = {"like": {}, "against": {}}
    entries: dict[str, dict[str, list[dict[str, str]]]] = {}
    for r in reasons:
        side = sides.get(r["type"])
        if side is None:
            continue
        for line in r["lines"]:
            key, wants = line.get("fact_key"), line.get("wants")
            if key is None:
                continue
            side.setdefault(key, set()).add(wants)
            if wants is not None:
                bucket = entries.setdefault(key, {"want": [], "avoid": []})["want" if wants else "avoid"]
                ref = {"reaction_id": r["reaction_id"], "side": r["type"]}
                if ref not in bucket:
                    bucket.append(ref)
    like, against = sides["like"], sides["against"]
    shared = set(like) & set(against)
    if not like or not against:
        conflict = "unclear"
    elif any(_opposite(like[k], against[k]) for k in shared):
        conflict = "same_axis"
    elif not shared:
        conflict = "different_axes"
    else:
        conflict = "unclear"
    keys = [
        {"fact_key": k, "want": sorted(v["want"], key=_ref_key), "avoid": sorted(v["avoid"], key=_ref_key)}
        for k, v in sorted(entries.items())
    ]
    return {"conflict_type": conflict, "keys": keys}


def _opposite(like_wants: set[bool | None], against_wants: set[bool | None]) -> bool:
    """♥ 쪽이 원하고 🚫 쪽이 피하거나, 그 반대인가."""
    return (True in like_wants and False in against_wants) or (False in like_wants and True in against_wants)


def _ref_key(ref: Mapping[str, str]) -> tuple[str, str]:
    return ref["side"], ref["reaction_id"]


def render_analysis(analysis: Mapping[str, Any] | None, fact_labels: Mapping[str, str]) -> AgentAnalysis | None:
    """저장된 compare_reasons 결과 → API의 AgentAnalysis. 축 이름은 키의 표시 이름이고, 이름을 모르는 키는 날것으로
    내지 않고 뺀다(추천 이유와 같은 규칙). 양쪽은 "원함 2", "원하지 않음 1"처럼 사람 수만."""
    if not analysis:
        return None
    axes = []
    for k in analysis.get("keys", []):
        label = fact_labels.get(k["fact_key"])
        if label is None:
            continue
        axes.append(AgentConflictAxis(
            label=label, like_side=_side_text(k, "like"), against_side=_side_text(k, "against"),
        ))
    return AgentAnalysis(conflict_type=analysis["conflict_type"], axes=axes)


def _side_text(key: Mapping[str, Any], side: str) -> str | None:
    want = sum(r["side"] == side for r in key["want"])
    avoid = sum(r["side"] == side for r in key["avoid"])
    parts = ([f"원함 {want}"] if want else []) + ([f"원하지 않음 {avoid}"] if avoid else [])
    return " / ".join(parts) or None


# ---------------------------------------------------------------- 모델 진단 검증 (11.2)

# 6절 표의 유형별 허용 행동
MODEL_ACTIONS = {"stall": ("open_recommend", "search_place", "show_pins"), "split": ("open_recommend", "show_pins")}
# 초안. 확정이나 결정을 지시하는 표현을 막는다(11.2). 공백을 뺀 문장과 비교한다. 검증(슬롯 문장)과 렌더 결과(인용이 채워진
# 문장) 두 곳에서 본다. "확정하라", "결정하라"는 사유 글 속 명령형("확정하라고 안내해")을 잡으려고 #534에서 더했다
FORBIDDEN_PHRASES = ("확정하세요", "확정해", "확정하라", "결정하세요", "결정하라", "여기로 가세요", "여기로 정하세요")
COPY_MIN_CHARS = 8   # 슬롯 밖에서 사유 원문과 공백을 뺀 연속 8글자 이상이 같으면 옮겨 쓴 것으로 본다(초안)
LINE_MAX_CHARS = 300   # AgentAdviceLine.text 상한

_CLAIM_ID = re.compile(r"c\d+")
_ALIAS = re.compile(r"(?<![A-Za-z0-9])m\d+(?![0-9])")
_SPACES = re.compile(r"\s+")
_SLOT = re.compile(r"\{(c\d+)(\.value)?\}")   # {cN.value}는 값, {cN}은 인용이나 참조(렌더도 같은 규칙)

# 모델 유형 제목 — 모델 출력에는 제목이 없어 코드가 정한다(카테고리 이름뿐, 숫자와 인용 없음)
_MODEL_TITLES = {
    "stall": lambda c: f"{c} 후보가 반대 의견 뒤로 멈춰 있어요",
    "split": lambda c: "의견이 갈린 핀이 있어요",
}


@dataclass(frozen=True)
class Verified:
    """verify_diagnosis 결과. outcome: suggested | silent | unknown | invalid_claims. record는 agent_runs.verification
    — 단계별 통과와 실패 내역이고, claim id와 이유만 담는다(사유 글 없음)."""
    outcome: str
    draft: Draft | None
    record: dict[str, Any]


def failed_outcome(reason: str) -> str:
    """AgentCallFailed.reason → agent_runs.outcome. 스키마 실패는 invalid_schema, 호출 실패와 타임아웃은 model_failed
    (data-model.md, #532). 어느 쪽도 재요청하지 않는다."""
    return "invalid_schema" if reason == "invalid_schema" else "model_failed"


def _normalize(text: str) -> str:
    return _SPACES.sub(" ", text).strip()


def _squash(text: str) -> str:
    return _SPACES.sub("", text)


def count_metric(snap: Snapshot, subject: str, subject_id: str | None, metric: str) -> int | None:
    """count claim을 스냅샷에서 다시 센다(11.2 3단계). 대상이 없으면 None(claim 제거).
    pin: like·against는 그 핀의 반응 수, unseen은 핀을 찍지 않은 구성원 중 반응하지 않은 사람 수, confirmed는 0/1,
    pins는 1. category와 map은 그 범위 핀들의 합이고, unseen은 반응하지 않은 구성원이 한 명이라도 있는 핀 수다."""
    if subject == "pin":
        found = snap.pin(subject_id) if subject_id else None
        pins = [found] if found is not None else None
    elif subject == "category":
        pins = [p for p in snap.pins if p.category == subject_id] if subject_id in categories.pinnable() else None
    else:
        pins = list(snap.pins) if subject_id is None else None
    if pins is None:
        return None
    if metric in ("like", "against"):
        return sum(r.type == metric for p in pins for r in snap.reactions_of(p.pin_id))
    if metric == "confirmed":
        return sum(snap.is_confirmed(p.pin_id) for p in pins)
    if metric == "pins":
        return len(pins)
    unseen = [
        sum(m.user_id != p.created_by and not snap.has_reaction(m.user_id, p.pin_id) for m in snap.members)
        for p in pins
    ]
    return unseen[0] if subject == "pin" else sum(n > 0 for n in unseen)


def resolve_path(result: Any, path: str) -> tuple[bool, Any]:
    """도구 결과 안의 경로("ready", "pins.0.reactions.m1"). 숫자 조각은 목록 위치다. (찾았나, 값)."""
    current = result
    for part in path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False, None
    return True, current


def _same_value(actual: Any, claimed: Any) -> bool:
    if isinstance(actual, bool) or isinstance(claimed, bool):   # True == 1을 같다고 보지 않는다
        return type(actual) is bool and type(claimed) is bool and actual == claimed
    if isinstance(actual, (int, float)) and isinstance(claimed, (int, float)):
        return actual == claimed
    return type(actual) is type(claimed) and actual == claimed


def _check_claim(claim: Any, snap: Snapshot, tool_results: Mapping[str, Any]) -> str | None:
    """claim 하나를 대조한다(11.2 3단계). 통과면 None, 아니면 이유."""
    if isinstance(claim, CountClaim):
        actual = count_metric(snap, claim.subject, claim.subject_id, claim.metric)
        return None if actual is not None and actual == claim.value else "count_mismatch"
    if isinstance(claim, QuoteClaim):
        reason = next((r for r in snap.reasons if r.reaction_id == claim.reaction_id), None)
        quote = _normalize(claim.text)
        if reason is None or not reason.text or not quote or quote not in _normalize(reason.text):
            return "quote_not_found"
        return None
    if isinstance(claim, RefClaim):
        if claim.object == "pin":
            found = snap.pin(claim.ref_id) is not None
        elif claim.object == "reaction":
            found = any(r.reaction_id == claim.ref_id for r in (*snap.reactions, *snap.reasons))
        else:
            found = any(p.place_id == claim.ref_id for p in snap.pins)
        return None if found else "ref_not_found"
    if isinstance(claim, ToolClaim):
        if claim.call_id not in tool_results:
            return "tool_call_not_found"
        found, actual = resolve_path(tool_results[claim.call_id], claim.path)
        return None if found and _same_value(actual, claim.value) else "tool_mismatch"
    return "unknown_kind"


def _verify_claims(out: DiagnosisOutput, snap: Snapshot, tool_results: Mapping[str, Any]):
    kept: dict[str, Any] = {}
    removed: list[dict[str, str]] = []
    seen: set[str] = set()
    for claim in out.claims:
        if not _CLAIM_ID.fullmatch(claim.id):
            reason = "bad_id"
        elif claim.id in seen:
            reason = "duplicate_id"
        else:
            reason = _check_claim(claim, snap, tool_results)
        seen.add(claim.id)
        if reason is None:
            kept[claim.id] = claim
        else:
            removed.append({"id": claim.id, "reason": reason})
            kept.pop(claim.id, None)   # 같은 id가 또 오면 앞의 것도 믿지 않는다
    return kept, removed


def _check_line(
    text: str, basis: Sequence[str], kept: Mapping[str, Any], reason_texts: Sequence[str], names: Sequence[str],
) -> str | None:
    """문장 하나(11.2 5단계). 통과면 None, 아니면 이유."""
    if any(b not in kept for b in basis):
        return "basis"
    for m in _SLOT.finditer(text):
        claim = kept.get(m.group(1))
        if claim is None:
            return "slot"
        if (m.group(2) is not None) != isinstance(claim, (CountClaim, ToolClaim)):
            return "slot"   # {cN.value}는 count와 tool_result, {cN}은 quote와 ref만
    bare = _SLOT.sub("", text)
    squashed = _squash(bare)
    if not squashed or len(text) > LINE_MAX_CHARS:
        return "empty_or_long"
    if "{" in bare or "}" in bare:
        return "slot"
    if any(name in text for name in names) or _ALIAS.search(text):
        return "member_name"   # 별칭(m3)에는 숫자가 있어 숫자 검사보다 먼저 본다
    if re.search(r"\d", bare):
        return "digit"
    if any(_squash(p) in squashed for p in FORBIDDEN_PHRASES):
        return "forbidden"
    windows = {squashed[i:i + COPY_MIN_CHARS] for i in range(len(squashed) - COPY_MIN_CHARS + 1)}
    if any(w in source for source in reason_texts for w in windows):
        return "copied"
    return None


def _model_action(
    action: Any, top: Signal, snap: Snapshot, kept: Mapping[str, Any],
) -> tuple[tuple[str, str, dict[str, Any]] | None, str | None]:
    """행동 하나(11.2 6단계) → ((type, label, params), None) 또는 (None, 이유). 버튼 이름은 코드가 정한다."""
    if action.type not in MODEL_ACTIONS[top.diagnosis]:
        return None, "type"
    if not action.basis or any(b not in kept for b in action.basis):
        return None, "basis"
    if action.type == "show_pins" and action.pin_ids:
        if any(snap.pin(pid) is None for pid in action.pin_ids):
            return None, "pin"
        return ("show_pins", "핀 보기", {"pin_ids": list(dict.fromkeys(action.pin_ids))}), None
    c = action.category or top.category
    if c not in categories.pinnable() or (action.type == "open_recommend" and c not in categories.recommendable()):
        return None, "category"
    label = {"open_recommend": f"{c} 추천 받기", "search_place": f"{c} 검색", "show_pins": f"{c} 핀 보기"}[action.type]
    return (action.type, label, {"category": c}), None


def _stored_claim(claim: Any) -> dict[str, Any]:
    """저장할 claim. quote의 text(대조용)는 버리고 reaction_id만 남긴다(명세 2절 13번, 11.2 끝)."""
    data = claim.model_dump()
    if isinstance(claim, QuoteClaim):
        data.pop("text")
    return data


def verify_diagnosis(
    out: DiagnosisOutput, top: Signal, snap: Snapshot, tool_results: Mapping[str, Any], *,
    member_names: Iterable[str] = (), comparison: Mapping[str, Any] | None = None,
) -> Verified:
    """모델 진단 출력 검증(11.2). 스키마(1단계)는 llm이 이미 봤다 — 여기 오는 것은 DiagnosisOutput이다.

    1 decision이 silent·unknown이면 그대로 침묵 2 signal_id와 diagnosis가 1순위 신호와 같은가 3 claim 대조(실패한
    claim 제거) 4 구조 대조(요약 전용이라 진단은 건너뛴다) 5 문장(제거된 claim을 가리킴, 슬롯 밖 숫자, 구성원 이름이나
    별칭, 금지 표현, 슬롯 밖 사유 원문 옮겨 쓰기) 6 행동(유형별 허용, 추천 대상 카테고리, basis) 7 성립(split은 그 핀의
    like·against count, 문장이나 행동이 하나 이상). 2단계나 7단계에서 실패하면 invalid_claims로 침묵한다.

    tool_results: 이번 관찰의 도구 결과(call_id → 모델에 준 결과 그대로). member_names: 구성원 표시 이름(두 글자
    이상만 본다 — 한 글자 이름은 보통 낱말과 겹친다)."""
    record: dict[str, Any] = {"decision": out.decision}
    if out.decision != "suggest":
        return Verified(out.decision, None, record)
    record["signal"] = out.signal_id == top.id and out.diagnosis == top.diagnosis
    if not record["signal"]:
        return Verified("invalid_claims", None, record | {"failed_step": 2})

    kept, removed = _verify_claims(out, snap, tool_results)
    record["claims"] = {"kept": list(kept), "removed": removed}
    record["structure"] = "skipped"

    names = [n for n in member_names if n and len(n) >= 2]
    reason_texts = [_squash(r.text) for r in snap.reasons if r.text]
    advice, removed_lines = [], []
    for i, line in enumerate(out.advice):
        reason = _check_line(line.text, line.basis, kept, reason_texts, names)
        if reason is None:
            advice.append({"slot_text": line.text, "is_guess": line.is_guess})
        else:
            removed_lines.append({"index": i, "reason": reason})
    record["lines"] = {"kept": len(advice), "removed": removed_lines}

    specs, removed_actions = [], []
    for i, action in enumerate(out.actions):
        spec, reason = _model_action(action, top, snap, kept)
        if reason is not None:
            removed_actions.append({"index": i, "reason": reason})
        elif spec not in specs:
            specs.append(spec)
    record["actions"] = {"kept": len(specs), "removed": removed_actions}

    required = top.diagnosis != "split" or all(
        any(isinstance(c, CountClaim) and c.subject == "pin" and c.subject_id == top.pin_id and c.metric == m
            for c in kept.values())
        for m in ("like", "against")
    )
    record["established"] = required and bool(advice or specs)
    if not record["established"]:
        return Verified("invalid_claims", None, record | {"failed_step": 7})
    draft = Draft(
        title=_MODEL_TITLES[top.diagnosis](top.category),
        claims=[_stored_claim(c) for c in kept.values()],
        advice=advice,
        actions=_actions(*specs),
        analysis=dict(comparison) if top.diagnosis == "split" and comparison else None,
    )
    return Verified("suggested", draft, record)


# ---------------------------------------------------------------- 렌더 (11절 끝 "저장과 렌더 시점")

@dataclass(frozen=True)
class RenderRefs:
    """렌더 때 읽은 지금 상태. 없는 키 = 지워졌다 → 그 키를 가리키는 문장을 뺀다."""
    pin_names: Mapping[str, str]   # 삭제되지 않은 핀 → 이름(db 핀은 장소 이름, 실시간 핀은 검색어)
    reaction_texts: Mapping[str, str] = field(default_factory=dict)   # 지금 있는 반응 → 사유 글
    fact_labels: Mapping[str, str] = field(default_factory=dict)   # 키 → 표시 이름(split 분석의 축 이름)


def referenced_pin_ids(claims: Sequence[Mapping[str, Any]]) -> list[str]:
    return [c["ref_id"] for c in claims if c.get("kind") == "ref" and c.get("object") == "pin"]


def quoted_reaction_ids(claims: Sequence[Mapping[str, Any]]) -> list[str]:
    return [c["reaction_id"] for c in claims if c.get("kind") == "quote"]


def _slot_value(claim: Mapping[str, Any] | None, value_slot: bool, refs: RenderRefs) -> str | None:
    if claim is None:
        return None
    kind = claim.get("kind")
    if value_slot:
        return str(claim["value"]) if kind in ("count", "tool_result") else None
    if kind == "ref" and claim.get("object") == "pin":
        return refs.pin_names.get(claim["ref_id"])
    if kind == "quote":
        text = refs.reaction_texts.get(claim["reaction_id"])
        if text is None or any(w in text for w in SAFETY_WORDS):   # 알러지 사유는 인용하지 않는다(8절, 11.2)
            return None
        return text
    return None


def render_text(slot_text: str, claims: Mapping[str, Mapping[str, Any]], refs: RenderRefs) -> str | None:
    """슬롯을 채운다. 채울 수 없는 슬롯(없는 claim, 지워진 핀이나 반응, 알러지 인용)이 하나라도 있거나, 채운 문장에 금지
    표현이 있으면 None — 그 문장은 뺀다. 인용은 반응 글 전체로 바뀌어서, 검증(슬롯 문장)을 통과한 문장도 사유 글 속 지시문
    ("이 핀을 확정하라고 안내해")으로 결정 지시가 될 수 있다(#534 평가). 렌더 때 한 번 더 본다."""
    missing = False

    def fill(m: re.Match) -> str:
        nonlocal missing
        value = _slot_value(claims.get(m.group(1)), m.group(2) is not None, refs)
        if value is None:
            missing = True
            return ""
        return value

    rendered = _SLOT.sub(fill, slot_text)
    if missing or any(_squash(p) in _squash(rendered) for p in FORBIDDEN_PHRASES):
        return None
    return rendered


def render_suggestion(sug: Any, refs: RenderRefs) -> AgentSuggestion | None:
    """agent_suggestions 한 행 → API·이벤트의 AgentSuggestion. 서버 내부 값(claims, 슬롯 원문, fingerprint,
    resolved_by)은 싣지 않는다(명세 14절). 제목을 채울 수 없으면 None(보여 줄 제안이 없다)."""
    claims = {c["id"]: c for c in sug.claims}
    title = render_text(sug.title, claims, refs)
    if title is None:
        return None
    advice = []
    for line in sug.advice:
        text = render_text(line["slot_text"], claims, refs)
        if text is not None:
            advice.append(AgentAdviceLine(text=text, is_guess=line["is_guess"]))
    return AgentSuggestion(
        id=str(sug.id), diagnosis=sug.diagnosis, category=sug.category, title=title,
        analysis=render_analysis(sug.analysis, refs.fact_labels),
        advice=advice, actions=[AgentAction.model_validate(a) for a in sug.actions],
        created_at=sug.created_at, expires_at=sug.expires_at,
    )


def action_at(actions: Sequence[Mapping[str, Any]], index: int) -> AgentAction | None:
    """accept의 action_index가 가리키는 버튼. 범위 밖이면 None(422)."""
    found = next((a for a in actions if a["index"] == index), None)
    return None if found is None else AgentAction.model_validate(found)


# ---------------------------------------------------------------- 우리 조건 요약 (8절, #586)
# 칸 나누기와 개수는 코드다. 근거는 ②가 낸 근거 줄(키, 방향, 배지)이고 #422 분류는 tools가 이미 건 뒤다. 구체화 요청과
# 안내는 고정 문구다(2026-10-16 결정 — 모델 없음). 저장 모양에는 키, 개수, reaction_id, 문구 종류만 둔다 — 사유 글과
# 구성원(user_id, 이름, 별칭)은 넣지 않는다(2절 11번, 13번). 키 이름과 문구는 응답과 이벤트를 만들 때 렌더한다.

FAR_CHIP_ID = "common_far"   # 「너무 멀어요」 — 키가 없어 vague_fixable, 거리 문구를 붙인다(8절 3번)
COMMON_PREF_MIN_MEMBERS = 2   # common_prefs: 같은 키, 같은 방향을 2명 이상
SUMMARY_REQUESTS = {   # vague_fixable 구체화 요청(고정 문구). 저장에는 종류(키)만 둔다
    "general": "어떤 점이 별로였는지 적어 주시면 추천에 반영돼요",
    "far": "거리 조건은 '숙소에서 걸어서 10분'처럼 적어 주세요",
}
SUMMARY_NOTICES = {   # not_filtered 고정 안내. 알러지 문구는 추천 결과 화면 안내(#425)와 같은 말이다
    "allergy": "알러지 같은 조건은 추천이 거르지 않아요. 가게에 직접 확인해 주세요.",
    "price": "가격은 아직 추천 조건에 없어요.",
}


def _first_reactions(snap: Snapshot) -> dict[str, tuple[datetime, str]]:
    """구성원 → 이 지도에서 가장 이른 반응의 (시각, 카테고리). 삭제된 핀의 반응은 사유가 있는 것만 보인다(별칭으로
    구성원을 찾는다). 반응 행에는 만든 시각이 없어 updated_at으로 본다 — 고친 반응은 고친 시각이다."""
    user_of = {m.alias: m.user_id for m in snap.members}
    acts = [(r.user_id, r.updated_at, snap.pin(r.pin_id).category) for r in snap.reactions if snap.pin(r.pin_id)]
    acts += [(user_of[r.alias], r.updated_at, r.category) for r in snap.reasons if r.pin_deleted and r.alias in user_of]
    first: dict[str, tuple[datetime, str]] = {}
    for user, at, category in sorted(acts, key=lambda a: a[1]):
        first.setdefault(user, (at, category))
    return first


def newcomer_reacted(snap: Snapshot, category: str, since: datetime | None) -> bool:
    """since 뒤에 첫 반응을 남긴 구성원이 있고 그 반응이 이 카테고리인가(8절 "새 구성원이 지도에서 첫 반응"). since가
    없으면(요약이 아직 없으면) 첫 반응이 이 카테고리인 구성원이 있는가."""
    return any(c == category and (since is None or at > since) for at, c in _first_reactions(snap).values())


def summary_changes(snap: Snapshot, category: str, meta: SummaryMeta | None) -> int | None:
    """그 카테고리 요약을 갱신해야 하면 바뀐 사유 수(새로 생긴 것 + 사라진 것), 아니면 None.

    - 새 사유가 SUMMARY_NEW_REASONS(3)개 이상. 새 사유 = 지금 사유 있는 반응 중 지난 요약이 보지 않은 것 — 지운 반응이
      없으면 명세의 "지금 수 - based_on_reaction_count"와 같고, 지운 반응이 있어도 새 사유를 놓치지 않는다.
    - 새 구성원이 지도에서 첫 반응을 이 카테고리에 남김(newcomer_reacted).
    - 지난 요약이 본 사유가 사라짐(반응 삭제, 지도 나가기 #369, 사유 지움). 지운 사람의 몫이 개수에 남지 않게 한다.
    요약이 없는 카테고리는 사유 있는 반응이 하나라도 있어야 만든다."""
    current = {r.reaction_id for r in snap.reasons if r.category == category}
    if meta is None and not current:
        return None
    known = meta.reaction_ids if meta is not None else frozenset()
    new, gone = current - known, known - current
    since = meta.updated_at if meta is not None else None
    if len(new) >= SUMMARY_NEW_REASONS or gone or newcomer_reacted(snap, category, since):
        return len(new) + len(gone)
    return None


def pick_summary(snap: Snapshot, metas: Sequence[SummaryMeta]) -> tuple[str | None, bool]:
    """이번 관찰에서 갱신할 카테고리 하나(8절, 초안)와 그 밖에 갱신할 카테고리가 더 있는지. 바뀐 사유가 가장 많은 것,
    같으면 categories.pinnable() 순서."""
    by_category = {m.category: m for m in metas}
    due = [(c, n) for c in categories.pinnable() if (n := summary_changes(snap, c, by_category.get(c))) is not None]
    if not due:
        return None, False
    return max(due, key=lambda d: d[1])[0], len(due) > 1


def _has_safety_word(text: str | None) -> bool:
    return bool(text) and any(w in text for w in SAFETY_WORDS)


def _keyless_kind(line: Mapping[str, Any], text: str | None) -> tuple[str, str] | None:
    """키 없는 줄(또는 방향 없는 줄) → (칸, 문구 종류). 칸에 넣지 않을 줄이면 None(8절 키 없는 사유 나누기).

    1. 칩은 id로 가른다: 「비싸요」 3종은 not_filtered(가격), 「너무 멀어요」는 vague_fixable(거리). 키 없는 칩의 이름에
       알러지 낱말이 있으면(뺀 칩 「갑각류 알러지가 있어요」, #425) not_filtered(알러지). 나머지 칩은 vague_fixable.
    2. 글에서 나온 키 없는 줄: 글에 SAFETY_WORDS가 있으면 None(그 글은 반응 단위로 알러지 칸에 이미 들어갔다), 아니면
       vague_fixable.
    3. 키는 있는데 방향이 없는 줄(wants=null)은 추천이 쓰지 않는다(constraints.md "wants가 null — 효과 없음"). 다시 적으면
       반영될 수 있어 vague_fixable로 둔다."""
    if line.get("source") == "chip":
        chip_id = line.get("chip_id")
        if chip_id in NOT_FILTERED_CHIP_IDS:
            return "not_filtered", "price"
        if chip_id == FAR_CHIP_ID:
            return "vague_fixable", "far"
        if line.get("fact_key") is None and _has_safety_word(line.get("label")):
            return "not_filtered", "allergy"
        return "vague_fixable", "general"
    if line.get("fact_key") is None and _has_safety_word(text):
        return None
    return "vague_fixable", "general"


def _item(key: tuple[str, bool], members: Mapping[str, set[str]]) -> dict[str, Any]:
    return {"fact_key": key[0], "wants": key[1], "member_count": len(members),
            "reaction_ids": sorted(set().union(*members.values()))}


def _by_count(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda i: (-i["member_count"], i["fact_key"], not i["wants"]))


def summarize_reasons(reasons: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """한 카테고리의 사유 있는 반응 → 저장할 다섯 칸(agent_reason_summaries.summary).

    reasons의 항목은 {reaction_id, member, text, lines}. member는 사람을 가르는 값(같은 사람 같은 키는 1명)일 뿐 저장하지
    않는다. text는 알러지 낱말을 보는 데만 쓰고 저장하지 않는다. lines는 tools.summary_reasons가 낸 근거 줄
    [{fact_key, wants, badge, source(text|chip), chip_id, label}] — #422 분류(음식 종류 "원함"은 preferred)는 이미 걸렸다.

    - must_keep: 배지 required이고 키와 방향이 있는 줄. 키와 방향마다 사람 수
    - split_prefs: 배지 preferred이고 같은 키에 원함과 피함이 함께 있는 키. 원함 사람 수, 피함 사람 수
    - common_prefs: 배지 preferred이고 같은 키, 같은 방향을 2명 이상(갈린 키는 split_prefs에만 둔다)
    - vague_fixable, not_filtered: 키 없는 사유(_keyless_kind). 개수는 반응 수, 문구는 종류만
    - reaction_ids: 이 요약이 본 사유 있는 반응 전부(다음 갱신 판단의 기준, summary_changes)"""
    must: dict[tuple[str, bool], dict[str, set[str]]] = {}
    prefs: dict[tuple[str, bool], dict[str, set[str]]] = {}
    keyless = {"vague_fixable": {"general": set(), "far": set()}, "not_filtered": {"allergy": set(), "price": set()}}
    for r in reasons:
        rid, member, text = r["reaction_id"], r["member"], r.get("text")
        if _has_safety_word(text):
            keyless["not_filtered"]["allergy"].add(rid)
        text_lines = [line for line in r["lines"] if line.get("source") != "chip"]
        if text and not text_lines and not _has_safety_word(text):   # ②가 줄을 내지 않은 글 — 키 없는 글과 같다
            keyless["vague_fixable"]["general"].add(rid)
        for line in r["lines"]:
            key, wants, badge = line.get("fact_key"), line.get("wants"), line.get("badge")
            if key is not None and wants is not None:
                bucket = must if badge == "required" else prefs if badge == "preferred" else None
                if bucket is not None:
                    bucket.setdefault((key, wants), {}).setdefault(member, set()).add(rid)
                continue
            kind = _keyless_kind(line, text)
            if kind is not None:
                keyless[kind[0]][kind[1]].add(rid)

    split_keys = sorted({k for k, w in prefs if (k, not w) in prefs})
    split = sorted(
        (
            {"fact_key": k, "want_count": len(prefs[(k, True)]), "avoid_count": len(prefs[(k, False)]),
             "want_reaction_ids": sorted(set().union(*prefs[(k, True)].values())),
             "avoid_reaction_ids": sorted(set().union(*prefs[(k, False)].values()))}
            for k in split_keys
        ),
        key=lambda i: (-(i["want_count"] + i["avoid_count"]), i["fact_key"]),
    )

    def section(name: str) -> dict[str, Any]:
        kinds = keyless[name]
        ids = sorted(set().union(*kinds.values()))
        field_name = "requests" if name == "vague_fixable" else "notices"
        return {"count": len(ids), "reaction_ids": ids, field_name: [k for k, v in kinds.items() if v]}

    return {
        "must_keep": _by_count([_item(k, m) for k, m in must.items()]),
        "common_prefs": _by_count([
            _item(k, m) for k, m in prefs.items() if k[0] not in split_keys and len(m) >= COMMON_PREF_MIN_MEMBERS
        ]),
        "split_prefs": split,
        "vague_fixable": section("vague_fixable"),
        "not_filtered": section("not_filtered"),
        "reaction_ids": sorted({r["reaction_id"] for r in reasons}),
    }


def summary_meta(category: str, summary: Mapping[str, Any], updated_at: datetime) -> SummaryMeta:
    return SummaryMeta(category=category, reaction_ids=frozenset(summary.get("reaction_ids", ())), updated_at=updated_at)


def render_summary(
    category: str, summary: Mapping[str, Any], updated_at: datetime, fact_labels: Mapping[str, str],
) -> AgentSummary:
    """저장된 다섯 칸 → API·이벤트의 AgentSummary. 이름은 개수만, 알러지 원문은 없다(2절 11번). 키 이름은
    recommend.api.fact_labels(근거 줄과 같은 이름)에 방향을 붙인다 — "매운맛 전문 제외", "조용한 곳 원함". 이름 모르는
    키는 뺀다(render_analysis와 같은 규칙)."""
    def item(i: Mapping[str, Any]) -> AgentSummaryItem | None:
        name = fact_labels.get(i["fact_key"])
        if name is None:
            return None
        return AgentSummaryItem(fact_key=i["fact_key"], label=f"{name} {'원함' if i['wants'] else '제외'}",
                                member_count=i["member_count"])

    def items(name: str) -> list[AgentSummaryItem]:
        return [x for x in (item(i) for i in summary.get(name, ())) if x is not None]

    vague, unfiltered = summary.get("vague_fixable", {}), summary.get("not_filtered", {})
    return AgentSummary(
        category=category,
        must_keep=items("must_keep"),
        common_prefs=items("common_prefs"),
        split_prefs=[
            AgentSplitPref(fact_key=s["fact_key"], label=fact_labels[s["fact_key"]], want_count=s["want_count"],
                           avoid_count=s["avoid_count"])
            for s in summary.get("split_prefs", ()) if s["fact_key"] in fact_labels
        ],
        vague_fixable=AgentVagueFixable(
            count=vague.get("count", 0), requests=[SUMMARY_REQUESTS[k] for k in vague.get("requests", ())],
        ),
        not_filtered=AgentNotFiltered(
            count=unfiltered.get("count", 0), notices=[SUMMARY_NOTICES[k] for k in unfiltered.get("notices", ())],
        ),
        updated_at=updated_at,
    )


# ---------------------------------------------------------------- 추천 막힘 조언 (9절, 10절, 11.2, #587)
# run 요청자 한 명에게 그 run의 데이터로만 조언한다(2절 2번의 예외). 대상 판정, 도구 결과 모양(근거 줄은 "본인"과 "다른 구성원"
# 으로만), 모델 출력 검증, 렌더가 여기 있다. 저장에는 슬롯 문장, 검증을 통과한 tool_result claim, 버튼(근거 줄은 line_id만)을
# 둔다 — 근거 글과 구성원 이름은 넣지 않는다(2절 11번, 13번). 조건을 끄는 것은 사람이다(가드레일 4): 버튼은 근거 확인 화면과
# 반경 넓히기로만 이어진다.

ADVICE_SELF, ADVICE_OTHER = "본인", "다른 구성원"   # 근거 줄을 쓴 사람. 이름과 user_id는 모델에 가지 않는다
PREFETCH_CALL_ID = "t0"   # 미리 읽어 입력에 넣는 깔때기의 call_id. llm이 매기는 t1, t2 …와 겹치지 않는다
RUN_ADVICE_ACTIONS: dict[str, tuple[str, ...]] = {   # 9절 표의 종류별 버튼
    "radius": ("widen_radius",), "soft_relax": ("open_evidence",), "vague_reason": ("open_evidence",), "exhausted": (),
}
RUN_ADVICE_LABELS = {   # 버튼 문구는 코드가 정한다. soft_relax 문구는 9절 그대로
    "radius": "반경 넓히기", "soft_relax": "근거 확인에서 빼 보기", "vague_reason": "근거 확인하기",
}


def run_advice_target(status: str, result_count: int, same_category_runs: int) -> bool:
    """조언 대상(9절): 완료된 run이고, 결과가 BLOCKED_RUN_MAX_RESULTS(3)곳 미만이거나 같은 요청자가 같은 카테고리 run을
    BLOCKED_RUN_MIN_SAME_CATEGORY_RUNS(3)개 이상 만들었다."""
    return status == "done" and (
        result_count < BLOCKED_RUN_MAX_RESULTS or same_category_runs >= BLOCKED_RUN_MIN_SAME_CATEGORY_RUNS
    )


def same_category_runs(recent: Sequence[Mapping[str, Any]], created_at: datetime) -> int:
    """같은 요청자, 같은 카테고리 run 중 이 run까지(created_at 이하) 만든 수 — 이 run 포함. 나중에 만든 run은 세지 않는다(같은
    run의 대상 여부가 뒤에 바뀌지 않게). recent는 recommend.api.get_recent_runs — 재시도 상한(#31, 10회)이 개인 단위라
    기본 10개로 그 사람의 run을 다 받는다."""
    return sum(r["created_at"] <= created_at for r in recent)


def radius_limits(walk_min: int, limit_walk_min: int) -> dict[str, Any]:
    """조언 입력의 반경: 지금 기본 반경(도보 분), 넓힐 수 있는 상한(WIDEN_LIMIT, 30분), 상한까지의 배율(소수 둘째 자리 내림).
    배율이 1 이하면 더 넓힐 수 없다."""
    factor = math.floor(limit_walk_min / walk_min * 100) / 100 if walk_min > 0 else 1.0
    return {"walk_min": walk_min, "max_walk_min": limit_walk_min, "max_radius_factor": factor}


def within_widen_limit(radius_factor: float | None, walk_min: int, limit_walk_min: int) -> bool:
    """반경 배율이 사람이 넓힐 수 있는 상한 안인가(가드레일 4 — 상한을 넘는 완화는 AI도 코드도 하지 않는다)."""
    return radius_factor is None or walk_min * radius_factor <= limit_walk_min + 1e-9


def funnel_view(outcome: Mapping[str, Any]) -> dict[str, Any]:
    """깔때기 도구 결과: 결과 수(최대 3), 단계별 탈락, passed(필터를 모두 통과한 곳 — 상위 3곳을 고르기 전). outcome은
    recommend.api.get_run_funnel 또는 simulate_filter의 before·after `{result_count, funnel, passed_count}`다. passed는
    recommend가 센 passed_count 그대로다 — 깔때기 라벨 글자로 셈하지 않는다(#587)."""
    return {
        "result_count": outcome["result_count"],
        "funnel": [{"label": e["label"], "removed_count": e["removed_count"]} for e in outcome["funnel"]],
        "passed": outcome["passed_count"],
    }


def simulate_view(
    raw: Mapping[str, Any], *, radius_factor: float | None, disable_line_ids: Sequence[str], walk_min: int,
    limit_walk_min: int,
) -> dict[str, Any]:
    """simulate_filter 도구 결과. 결과 수는 상위 3곳 뒤라 최대 3이어서 비교는 passed로 한다 — gained = after.passed −
    before.passed(같은 호출의 before와 after끼리, #585). within_widen_limit이 거짓인 결과를 가리키는 claim은 검증에서 빠진다."""
    before, after = funnel_view(raw["before"]), funnel_view(raw["after"])
    return {
        "radius_factor": radius_factor, "disable_line_ids": list(disable_line_ids),
        "within_widen_limit": within_widen_limit(radius_factor, walk_min, limit_walk_min),
        "before": before, "after": after, "gained": after["passed"] - before["passed"],
    }


def recent_runs_view(recent: Sequence[Mapping[str, Any]], run_id: str) -> list[dict[str, Any]]:
    return [
        {"run_id": r["run_id"], "status": r["status"], "result_count": r["result_count"],
         "created_at": r["created_at"].isoformat(), "this_run": r["run_id"] == run_id}
        for r in recent
    ]


def evidence_kind(line: Mapping[str, Any]) -> str:
    """근거 줄의 종류(9절 표, 8절 키 없는 사유 나누기): condition(키가 있다), not_filtered(키가 없고 「비싸요」 칩이거나 글에 알러지
    낱말이 있다 — 추천이 거르지 않는 줄이라 vague_reason에서 세지 않는다), vague(그 밖의 키 없는 줄)."""
    if line.get("fact_key") is not None:
        return "condition"
    if line.get("chip_id") in NOT_FILTERED_CHIP_IDS or _has_safety_word(line.get("text")):
        return "not_filtered"
    return "vague"


def _condition_label(fact_key: str | None, wants: bool | None, fact_labels: Mapping[str, str]) -> str | None:
    name = fact_labels.get(fact_key) if fact_key else None
    if name is None or wants is None:
        return name
    return f"{name} {'원함' if wants else '제외'}"   # 요약(render_summary)과 같은 말


def advice_evidence(
    lines: Sequence[Mapping[str, Any]], requester_id: str, fact_labels: Mapping[str, str],
) -> list[dict[str, Any]]:
    """get_run_evidence 도구 결과의 줄. 쓴 사람은 "본인" 또는 "다른 구성원"으로만 나온다(이름, user_id 없음). label은 코드가 만든
    조건 이름이라 문장 슬롯으로 쓸 수 있다. not_filtered 줄은 글을 싣지 않는다(알러지 원문, 2절 11번)."""
    out = []
    for line in lines:
        kind = evidence_kind(line)
        out.append({
            "line_id": line["line_id"], "author": ADVICE_SELF if line["author_id"] == requester_id else ADVICE_OTHER,
            "badge": line["badge"], "fact_key": line["fact_key"], "wants": line["wants"],
            "label": _condition_label(line["fact_key"], line["wants"], fact_labels), "is_active": line["is_active"],
            "kind": kind, "text": None if kind == "not_filtered" else line["text"],
        })
    return out


def advice_input(meta: Mapping[str, Any], same_runs: int, funnel_result: Mapping[str, Any]) -> dict[str, Any]:
    """llm.agent_advise_run에 넘길 입력. 그 run의 깔때기를 미리 넣어(call_id t0) 모델이 get_run_funnel을 부르지 않고도 claim을
    쓸 수 있게 한다. 근거 글, 구성원, run_id는 넣지 않는다(근거 줄은 get_run_evidence로, run은 tool_runner가 채운다)."""
    return {
        "category": meta["category"], "result_count": meta["result_count"], "same_category_runs": same_runs,
        "radius": radius_limits(meta["default_radius_walk_min"], meta["widen_limit_walk_min"]),
        "funnel": {"call_id": PREFETCH_CALL_ID, "result": dict(funnel_result)},
    }


@dataclass(frozen=True)
class AdviceDraft:
    """agent_run_advice에 저장할 조언. kind가 None이면 빈 조언(침묵, 실패, 검증 실패)이다 — 그래도 저장해 다시 만들지 않는다."""
    kind: str | None
    claims: list[dict[str, Any]]
    advice: list[dict[str, Any]]    # [{slot_text, is_guess}]
    actions: list[dict[str, Any]]   # [{index, type, label, params}] — AgentAction 직렬화


EMPTY_ADVICE = AdviceDraft(None, [], [], [])


@dataclass(frozen=True)
class VerifiedAdvice:
    """verify_run_advice 결과. outcome: advised | silent | unknown | invalid_claims. record는 agent_runs.verification."""
    outcome: str
    draft: AdviceDraft
    record: dict[str, Any]


@dataclass(frozen=True)
class AdviceContext:
    """검증이 보는 이번 조언의 사실. tool_results와 tool_names는 call_id(미리 읽은 t0 포함) → 모델에 준 결과, 도구 이름.
    own_lines는 그 run의 근거 줄 → 요청자 본인이 쓴 줄인가. evidence_texts는 근거 글(옮겨 쓰기 검사용, 저장하지 않는다)."""
    run_id: str
    tool_results: Mapping[str, Any]
    tool_names: Mapping[str, str]
    own_lines: Mapping[str, bool]
    evidence_texts: Sequence[str]
    radius: Mapping[str, Any]
    member_names: Sequence[str] = ()


def _tool_of(claim: ToolClaim, ctx: AdviceContext) -> tuple[str | None, Mapping[str, Any]]:
    result = ctx.tool_results.get(claim.call_id)
    return ctx.tool_names.get(claim.call_id), result if isinstance(result, Mapping) else {}


def _advice_claim_reason(claim: Any, ctx: AdviceContext) -> str | None:
    """claim 하나(11.2 3단계를 조언에 맞게). 조언은 tool_result claim만 쓴다 — 핀 개수, 인용, 참조는 없다. 근거 글(text)을
    가리키는 claim은 렌더하면 원문이 나가서 뺀다. 반경 상한을 넘는 시뮬레이션 결과도 뺀다(가드레일 4)."""
    if not isinstance(claim, ToolClaim):
        return "kind"
    if claim.path.split(".")[-1] == "text":
        return "text_path"
    reason = _check_claim(claim, None, ctx.tool_results)
    if reason is not None:
        return reason
    name, result = _tool_of(claim, ctx)
    if name == "simulate_filter" and not result.get("within_widen_limit", False):
        return "radius_over_limit"
    return None


def _claim_line_ids(claim: ToolClaim, ctx: AdviceContext) -> list[str]:
    """claim이 가리키는 근거 줄 — 줄을 끈 시뮬레이션이면 그 줄들, 근거 줄 목록의 한 줄(lines.N.…)이면 그 줄."""
    name, result = _tool_of(claim, ctx)
    if name == "simulate_filter":
        return list(result.get("disable_line_ids") or ())
    parts = claim.path.split(".")
    if name == "get_run_evidence" and len(parts) >= 2 and parts[0] == "lines":
        found, line = resolve_path(result, f"lines.{parts[1]}")
        if found and isinstance(line, Mapping) and line.get("line_id"):
            return [line["line_id"]]
    return []


def _widens(claim: ToolClaim, ctx: AdviceContext) -> bool:
    name, result = _tool_of(claim, ctx)
    return name == "simulate_filter" and (result.get("radius_factor") or 0) > 1


def _advice_action(
    action: Any, kind: str, kept: Mapping[str, ToolClaim], ctx: AdviceContext,
) -> tuple[tuple[str, str, dict[str, Any]] | None, str | None]:
    """버튼 하나(11.2 6단계를 조언에 맞게) → ((type, label, params), None) 또는 (None, 이유).
    - 종류별 허용(radius는 widen_radius, soft_relax와 vague_reason은 open_evidence, exhausted는 없음)과 basis.
    - widen_radius: 반경 상한 안에서 넓힌 시뮬레이션 claim이 basis에 있어야 하고, 이미 상한이면 뺀다.
    - open_evidence: basis가 가리키는 근거 줄이 모두 요청자 본인 줄이어야 한다. 남의 줄이 하나라도 있으면 버튼을 뺀다 — 근거
      줄 빼기는 쓴 사람만 할 수 있다(9절, permissions의 evidence.disable). 문장은 따로 검사해 남는다."""
    if action.type not in RUN_ADVICE_ACTIONS[kind]:
        return None, "type"
    if not action.basis or any(b not in kept for b in action.basis):
        return None, "basis"
    basis = [kept[b] for b in action.basis]
    if action.type == "widen_radius":
        if ctx.radius["max_radius_factor"] <= 1:
            return None, "radius_limit"
        if not any(_widens(c, ctx) for c in basis):
            return None, "no_simulation"
        return ("widen_radius", RUN_ADVICE_LABELS[kind], {"run_id": ctx.run_id}), None
    line_ids = list(dict.fromkeys(i for c in basis for i in _claim_line_ids(c, ctx)))
    if not line_ids:
        return None, "no_line"
    if not all(ctx.own_lines.get(i) for i in line_ids):
        return None, "not_own_line"
    return ("open_evidence", RUN_ADVICE_LABELS[kind], {"run_id": ctx.run_id, "evidence_line_ids": line_ids}), None


def _advice_established(kind: str, kept: Mapping[str, ToolClaim], ctx: AdviceContext) -> bool:
    """종류의 필수 claim(11.2 7단계를 조언에 맞게): radius는 넓힌 시뮬레이션, soft_relax는 줄을 끈 시뮬레이션, vague_reason은
    근거 줄 목록, exhausted는 깔때기."""
    if kind == "radius":
        return any(_widens(c, ctx) for c in kept.values())
    tools = [_tool_of(c, ctx) for c in kept.values()]
    if kind == "soft_relax":
        return any(name == "simulate_filter" and result.get("disable_line_ids") for name, result in tools)
    wanted = "get_run_evidence" if kind == "vague_reason" else "get_run_funnel"
    return any(name == wanted for name, _ in tools)


def verify_run_advice(out: RunAdviceOutput, ctx: AdviceContext) -> VerifiedAdvice:
    """추천 막힘 조언 검증(11.2를 조언에 맞게). 스키마(1단계)와 kind 네 가지는 llm이 이미 봤다.

    1 decision이 silent·unknown이면 그대로 침묵 3 claim(tool_result만, 근거 글 경로 금지, 도구 결과와 같은 값, 반경 상한 안)
    5 문장(제거된 claim을 가리킴, 슬롯 밖 숫자, 구성원 이름, 금지 표현, 슬롯 밖에서 근거 글 옮겨 쓰기 — 진단과 같은 _check_line)
    6 버튼(종류별 허용, 반경 상한, 요청자 본인 줄) 7 성립(종류의 필수 claim, 문장이나 버튼이 하나 이상). 7단계에서 떨어지면
    invalid_claims로 침묵한다. 2단계(신호)와 4단계(요약 구조)는 조언에 없다."""
    record: dict[str, Any] = {"decision": out.decision, "kind": out.kind}
    if out.decision != "suggest":
        return VerifiedAdvice(out.decision, EMPTY_ADVICE, record)

    kept: dict[str, ToolClaim] = {}
    removed: list[dict[str, str]] = []
    seen: set[str] = set()
    for claim in out.claims:
        if not _CLAIM_ID.fullmatch(claim.id):
            reason = "bad_id"
        elif claim.id in seen:
            reason = "duplicate_id"
        else:
            reason = _advice_claim_reason(claim, ctx)
        seen.add(claim.id)
        if reason is None:
            kept[claim.id] = claim
        else:
            removed.append({"id": claim.id, "reason": reason})
            kept.pop(claim.id, None)   # 같은 id가 또 오면 앞의 것도 믿지 않는다
    record["claims"] = {"kept": list(kept), "removed": removed}

    names = [n for n in ctx.member_names if n and len(n) >= 2]
    texts = [_squash(t) for t in ctx.evidence_texts if t]
    advice, removed_lines = [], []
    for i, line in enumerate(out.advice):
        reason = _check_line(line.text, line.basis, kept, texts, names)
        if reason is None:
            advice.append({"slot_text": line.text, "is_guess": line.is_guess})
        else:
            removed_lines.append({"index": i, "reason": reason})
    record["lines"] = {"kept": len(advice), "removed": removed_lines}

    specs, removed_actions = [], []
    for i, action in enumerate(out.actions):
        spec, reason = _advice_action(action, out.kind, kept, ctx)
        if reason is not None:
            removed_actions.append({"index": i, "reason": reason})
        elif spec not in specs:
            specs.append(spec)
    record["actions"] = {"kept": len(specs), "removed": removed_actions}

    record["established"] = _advice_established(out.kind, kept, ctx) and bool(advice or specs)
    if not record["established"]:
        return VerifiedAdvice("invalid_claims", EMPTY_ADVICE, record | {"failed_step": 7})
    draft = AdviceDraft(kind=out.kind, claims=[c.model_dump() for c in kept.values()], advice=advice,
                        actions=_actions(*specs))
    return VerifiedAdvice("advised", draft, record)


def render_run_advice(run_id: str, row: Any) -> RunAdvice | None:
    """agent_run_advice 한 행 → API의 RunAdvice. 빈 조언(kind 없음)이거나 렌더 뒤 문장과 버튼이 모두 없으면 None(204). 슬롯은
    tool_result 값만 채운다 — 근거 글은 저장에도 응답에도 없다. 금지 표현은 렌더 결과에도 건다(render_text)."""
    if row is None or row.kind is None:
        return None
    claims = {c["id"]: c for c in row.claims}
    refs = RenderRefs(pin_names={})
    advice = []
    for line in row.advice:
        text = render_text(line["slot_text"], claims, refs)
        if text is not None:
            advice.append(AgentAdviceLine(text=text, is_guess=line["is_guess"]))
    actions = [AgentAction.model_validate(a) for a in row.actions]
    if not advice and not actions:
        return None
    return RunAdvice(run_id=run_id, kind=row.kind, advice=advice, actions=actions)


# ---------------------------------------------------------------- 응답 조립 (14절)

def settings_view(row: Any | None) -> AgentSettings:
    """agent_settings 행 → AgentSettings. 행이 없으면 기본값 켜짐, 바꾼 사람 없음."""
    if row is None:
        return AgentSettings(enabled=True, updated_by=None, updated_at=None)
    return AgentSettings(enabled=row.enabled, updated_by=row.updated_by, updated_at=row.updated_at)


def agent_state(
    settings: AgentSettings, active: AgentSuggestion | None, *, viewed: bool, summaries: Sequence[AgentSummary] = (),
) -> AgentState:
    """모드가 꺼져 있으면 제안은 늘 null이고 점도 없다. 요약은 모드와 상관없이 만들어진 카테고리만 싣는다(api-spec
    AgentState.summaries — 끄면 관찰이 멈춰 더 갱신되지 않을 뿐이다)."""
    shown = active if settings.enabled else None
    return AgentState(settings=settings, active_suggestion=shown, has_unseen=shown is not None and not viewed,
                      summaries=list(summaries))


# ---------------------------------------------------------------- 이벤트 (15절)

def suggested_event(map_id: str, suggestion: AgentSuggestion) -> Event:
    return Event(map_id=map_id, channel="public", type="agent.suggested", payload=suggestion.model_dump(mode="json"))


def resolved_event(map_id: str, suggestion_id: str, status: str, action_type: str | None = None) -> Event:
    """누가 처리했는지(resolved_by)는 싣지 않는다(15절)."""
    return Event(map_id=map_id, channel="public", type="agent.resolved",
                 payload={"suggestion_id": suggestion_id, "status": status, "resolved_action_type": action_type})


def settings_changed_event(map_id: str, enabled: bool, updated_by: str) -> Event:
    return Event(map_id=map_id, channel="public", type="agent.settings_changed",
                 payload={"enabled": enabled, "updated_by": updated_by})


def summary_updated_event(map_id: str, summary: AgentSummary) -> Event:
    """점이나 알림은 켜지 않는다(15절) — FE는 그 카테고리 요약만 갈아끼운다."""
    return Event(map_id=map_id, channel="public", type="agent.summary_updated", payload=summary.model_dump(mode="json"))
