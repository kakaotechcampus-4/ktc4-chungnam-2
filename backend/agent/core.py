"""계획 보조 에이전트의 판단 — 순수 함수만 둔다. DB를 모르고 시각은 인자로 받는다(docs/code-quality.md 기능형 코어).

- 기준 시간(명세 6.1), 탐지기 4종(6.2~6.5), 신호(Signal)와 해시(3절)
- 개입 정책(12.3), 대체 순위(7절), 다음 점검 시각(12.4)
- 우선순위 정책 파일(`priority_policy.yaml`) 로더 — 파일 읽기 한 곳만 I/O다

입력은 `agent.snapshot.Snapshot`(관찰 한 번의 사본)과 `History`(이 지도의 제안 이력, #515가 채운다)다.
Signal과 features에는 사유 글을 넣지 않는다 — 근거는 reaction_id와 pin_id로만 가리킨다(명세 2절 13번).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
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
    STALL_ACTIVE_MEMBERS,
    TIME_MAX,
    TIME_MIN,
    TIME_MULTIPLIER,
)
from common import categories

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
    reason: str   # active_exists | duplicate | backoff | daily_limit | model_cap


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
