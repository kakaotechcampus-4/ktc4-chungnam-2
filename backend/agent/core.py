"""계획 보조 에이전트의 판단 — 순수 함수만 둔다. DB를 모르고 시각은 인자로 받는다(docs/code-quality.md 기능형 코어).

- 기준 시간(명세 6.1), 탐지기 4종(6.2~6.5), 신호(Signal)와 해시(3절)
- 개입 정책(12.3), 대체 순위(7절), 다음 점검 시각(12.4)
- 우선순위 정책 파일(`priority_policy.yaml`) 로더 — 파일 읽기 한 곳만 I/O다
- 코드 유형 템플릿(6.4, 6.5)과 렌더(11절 끝 "저장과 렌더 시점"), 이벤트 페이로드(15절) — #531

입력은 `agent.snapshot.Snapshot`(관찰 한 번의 사본)과 `History`(이 지도의 제안 이력, #515가 채운다)다.
Signal과 features에는 사유 글을 넣지 않는다 — 근거는 reaction_id와 pin_id로만 가리킨다(명세 2절 13번).
"""

from __future__ import annotations

import hashlib
import json
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
    CATEGORY_GAP_MIN_CONFIRMED,
    CODE_TYPES,
    DDAY_FACTOR_FAR,
    DDAY_FACTOR_MID,
    DDAY_FACTOR_NEAR,
    DDAY_FAR,
    DDAY_MID,
    MODEL_TYPES,
    NO_REACTION_DAILY_LIMIT,
    NO_REACTION_MIN_TARGET_PINS,
    NO_REACTION_UNSEEN_RATIO,
    PER_MEMBER_DAILY_MODEL_USES,
    RHYTHM_DEFAULT_BASE,
    RHYTHM_MIN_EVENTS,
    RHYTHM_WINDOW_EVENTS,
    SAFETY_WORDS,
    SHADOW_DIAGNOSES,
    STALL_ACTIVE_MEMBERS,
    TIME_MAX,
    TIME_MIN,
    TIME_MULTIPLIER,
)
from agent.schemas import (
    AgentAction,
    AgentAdviceLine,
    AgentSettings,
    AgentState,
    AgentSuggestion,
    CountClaim,
    RefClaim,
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
class History:
    suggestions: tuple[PastSuggestion, ...] = ()   # 이 지도, 최신순(created_at 내림차순)
    model_runs_today: int = 0   # KST 자정 이후 used_model=true이고 trigger in (activity, time, summary)인 agent_runs 수

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


# ---------------------------------------------------------------- 우선순위 정책 (7절)

POLICY_PATH = Path(__file__).with_name("priority_policy.yaml")


@dataclass(frozen=True)
class PriorityPolicy:
    version: int
    principles: tuple[str, ...]
    never_first: tuple[str, ...]
    always_first: tuple[str, ...]
    weights: Mapping[str, int]


def parse_policy(raw: Mapping[str, Any]) -> PriorityPolicy:
    """weights에 diagnosis 4종이 모두 있어야 하고, rules에는 아는 diagnosis만 올 수 있다. 어긋나면 ValueError."""
    weights = dict(raw.get("weights") or {})
    if set(weights) != set(DIAGNOSES):
        raise ValueError(f"priority_policy weights는 {sorted(DIAGNOSES)}를 모두 가져야 한다: {sorted(weights)}")
    if not all(isinstance(w, int) and not isinstance(w, bool) for w in weights.values()):
        raise ValueError(f"priority_policy weights는 정수여야 한다: {weights}")
    rules = raw.get("rules") or {}
    never_first = tuple(rules.get("never_first") or ())
    always_first = tuple(rules.get("always_first") or ())
    unknown = set(never_first + always_first) - set(DIAGNOSES)
    if unknown:
        raise ValueError(f"priority_policy rules에 모르는 diagnosis: {sorted(unknown)}")
    return PriorityPolicy(
        version=int(raw["version"]), principles=tuple(raw.get("principles") or ()),
        never_first=never_first, always_first=always_first, weights=weights,
    )


@lru_cache(maxsize=1)
def load_policy(path: Path = POLICY_PATH) -> PriorityPolicy:
    with open(path, encoding="utf-8") as f:
        return parse_policy(yaml.safe_load(f))


def fallback_order(signals: Sequence[Signal], policy: PriorityPolicy) -> list[Signal]:
    """모델 없이 정하는 순위(7절 3번): weights 내림차순, 동점이면 elapsed_ratio 내림차순(없으면 뒤), 그래도 같으면
    탐지 순서."""
    def key(sig: Signal):
        ratio = sig.features.get("elapsed_ratio")
        return (-policy.weights[sig.diagnosis], ratio is None, -(ratio or 0.0))
    return sorted(signals, key=key)


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


def choose_top(passed: Sequence[Signal], policy: PriorityPolicy) -> tuple[Signal | None, dict[str, Any] | None]:
    """1순위 신호와 agent_runs.priority 기록(7절). M0은 모델을 부르지 않아 늘 fallback_order다(model_order 없음).
    M1에서 신호가 2개 이상이면 llm.agent_prioritize와 apply_priority_rules로 바뀐다."""
    if not passed:
        return None, None
    order = fallback_order(passed, policy)
    log = {"model_order": None, "final_order": [s.id for s in order], "corrections": [], "reused": False}
    return order[0], log


def signal_record(sig: Signal) -> dict[str, Any]:
    """agent_runs.signals 한 칸. 근거는 id로만 담고 사유 글은 없다(명세 2절 13번)."""
    return {
        "id": sig.id, "diagnosis": sig.diagnosis, "category": sig.category, "pin_id": sig.pin_id,
        "evidence_ids": list(sig.evidence_ids), "features": dict(sig.features),
        "fingerprint": sig.fingerprint, "evidence_hash": sig.evidence_hash,
    }


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


# ---------------------------------------------------------------- 렌더 (11절 끝 "저장과 렌더 시점")

_SLOT = re.compile(r"\{(c\d+)(\.value)?\}")


@dataclass(frozen=True)
class RenderRefs:
    """렌더 때 읽은 지금 상태. 없는 키 = 지워졌다 → 그 키를 가리키는 문장을 뺀다."""
    pin_names: Mapping[str, str]   # 삭제되지 않은 핀 → 이름(db 핀은 장소 이름, 실시간 핀은 검색어)
    reaction_texts: Mapping[str, str] = field(default_factory=dict)   # 지금 있는 반응 → 사유 글


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
    """슬롯을 채운다. 채울 수 없는 슬롯(없는 claim, 지워진 핀이나 반응, 알러지 인용)이 하나라도 있으면 None — 그
    문장은 뺀다."""
    missing = False

    def fill(m: re.Match) -> str:
        nonlocal missing
        value = _slot_value(claims.get(m.group(1)), m.group(2) is not None, refs)
        if value is None:
            missing = True
            return ""
        return value

    rendered = _SLOT.sub(fill, slot_text)
    return None if missing else rendered


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
        id=str(sug.id), diagnosis=sug.diagnosis, category=sug.category, title=title, analysis=sug.analysis,
        advice=advice, actions=[AgentAction.model_validate(a) for a in sug.actions],
        created_at=sug.created_at, expires_at=sug.expires_at,
    )


def action_at(actions: Sequence[Mapping[str, Any]], index: int) -> AgentAction | None:
    """accept의 action_index가 가리키는 버튼. 범위 밖이면 None(422)."""
    found = next((a for a in actions if a["index"] == index), None)
    return None if found is None else AgentAction.model_validate(found)


# ---------------------------------------------------------------- 응답 조립 (14절)

def settings_view(row: Any | None) -> AgentSettings:
    """agent_settings 행 → AgentSettings. 행이 없으면 기본값 켜짐, 바꾼 사람 없음."""
    if row is None:
        return AgentSettings(enabled=True, updated_by=None, updated_at=None)
    return AgentSettings(enabled=row.enabled, updated_by=row.updated_by, updated_at=row.updated_at)


def agent_state(settings: AgentSettings, active: AgentSuggestion | None, *, viewed: bool) -> AgentState:
    """모드가 꺼져 있으면 제안은 늘 null이고 점도 없다. 요약은 M2 전까지 빈 목록."""
    shown = active if settings.enabled else None
    return AgentState(settings=settings, active_suggestion=shown, has_unseen=shown is not None and not viewed,
                      summaries=[])


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
