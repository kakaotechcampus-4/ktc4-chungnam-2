"""agent 평가셋(#534) — cases.json의 지도 상태를 agent가 보는 모양(Snapshot, 신호, 도구 결과)으로 바꾼다. DB를 쓰지 않는다.

- 지도 상태는 실제 관찰과 같은 코드로 읽는다: 신호는 agent.core.detect_all과 check_policy, 진단 입력은 core.diagnosis_input,
  충돌 종류는 core.compare_reasons, 검증은 core.verify_diagnosis다. 평가가 보는 것은 프롬프트와 모델이고, 탐지와 검증 규칙은
  운영과 같다.
- 도구는 agent/tools.py와 같은 모양의 결과를 픽스처에서 만든다(FixtureTools). structure_reasons는 ②를 부르지 않고 픽스처의
  lines(②가 냈을 키와 방향)와 칩 표를 쓴다 — 평가 대상이 ②가 아니라서다.
- 사유 글은 지어낸 예시다. 실제 사용자 글을 넣지 않는다.

평가 도구라 agent의 core와 snapshot(api.py가 아닌 모듈)을 직접 가져온다. 운영 코드는 이 파일을 가져오지 않는다.
"""

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from agent import core
from agent.snapshot import Chip, MapInfo, Member, Pin, Reaction, Reason, ShortlistItem, Snapshot, derive_actions
from common import categories

CASES_PATH = Path(__file__).with_name("cases.json")

NOW = datetime(2026, 10, 15, 3, 0, tzinfo=timezone.utc)   # KST 12:00 (agent/tests/snaps.py와 같은 시각)
TODAY = date(2026, 10, 15)
JOINED = NOW - timedelta(hours=240)
# 검증 5단계가 문장에서 찾는 표시 이름(지어낸 이름). 모델에는 가지 않는다
MEMBER_NAMES = ("김하늘", "이도윤", "박서연", "최지호", "정민준", "한유진")

# docs/constraints.md 칩 표에서 평가셋이 쓰는 것만(id → label, fact_key, wants)
CHIPS: dict[str, tuple[str, str | None, bool | None]] = {
    "food_spicy": ("매워요", "spicy_focused", False),
    "food_oily": ("느끼해요", "oily_focused", False),
    "food_expensive": ("비싸요", None, None),
    "food_wait": ("웨이팅이 길어요", "wait_short", True),
    "food_cramped": ("좁아요", "spacious", True),
    "cafe_crowded": ("너무 붐벼요", "is_crowded_large", False),
    "cafe_noisy": ("시끄러워요", "quiet", True),
    "cafe_seat": ("자리가 불편해요", "comfortable_seat", True),
    "sight_inaccessible": ("휠체어·유모차로 가기 힘들어요", "accessible", True),
    "sight_noisy": ("시끄러워요", "quiet", True),
    "common_not_my_taste": ("취향이 아니에요", None, None),
    "common_far": ("너무 멀어요", None, None),
}


def load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _ago(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


def signal_key(sig: core.Signal) -> str:
    """신호의 사람용 이름 — 평가셋 기대값과 맞춘다. stall과 category_gap은 카테고리, split은 핀 id."""
    if sig.diagnosis == "split":
        return f"split:{sig.pin_id}"
    if sig.diagnosis == "no_reaction":
        return "no_reaction"
    return f"{sig.diagnosis}:{sig.category}"


@dataclass
class World:
    """케이스 하나의 지도 상태."""
    case: dict[str, Any]
    snap: Snapshot
    names: dict[str, str]                          # pin_id → 장소 이름(실시간 핀은 검색어)
    lines: dict[str, list[dict[str, Any]]]         # reaction_id → ②가 냈을 줄(글에서 나온 것만)
    facts: dict[str, dict[str, Any]]               # place_id → {fact_key: value}
    history: core.History = field(default_factory=core.History)

    @property
    def th(self) -> timedelta:
        return core.time_threshold(self.snap.action_times, self.snap.map.start_date, self.snap.today)

    def signals(self) -> list[core.Signal]:
        return core.detect_all(self.snap, NOW, self.th)

    def passed(self) -> tuple[list[core.Signal], list[core.Blocked]]:
        signals = self.signals()
        return core.check_policy(signals, self.history, self.snap, NOW, superseding=core.find_superseded(None, signals))

    def find(self, key: str) -> core.Signal:
        passed, _ = self.passed()
        return next(s for s in passed if signal_key(s) == key)

    def structured(self, reaction_ids: list[str]) -> list[dict[str, Any]]:
        """structure_reasons 모양 [{reaction_id, type, lines}]. 글 줄(픽스처) + 칩 줄(칩 표). 🚫 글은 required, ♥ 글은
        preferred, 칩은 required — agent/tools._structured와 같다(#422 강등은 평가에서 보지 않는다)."""
        out = []
        by_id = {r.reaction_id: r for r in self.snap.reasons}
        for rid in reaction_ids:
            r = by_id.get(rid)
            if r is None:
                continue
            badge = "required" if r.type == "against" else "preferred"
            rows = [{"fact_key": ln["fact_key"], "wants": ln.get("wants"), "badge": badge} for ln in self.lines.get(rid, [])]
            rows += [{"fact_key": c.fact_key, "wants": c.wants, "badge": "required"} for c in r.chips]
            out.append({"reaction_id": rid, "type": r.type, "lines": rows})
        return out

    def comparison(self, pin_id: str) -> dict[str, Any]:
        return core.compare_reasons(self.structured([r.reaction_id for r in self.snap.reasons if r.pin_id == pin_id]))

    def diagnosis_input(self, key: str) -> dict[str, Any]:
        top = self.find(key)
        comparison = self.comparison(top.pin_id) if top.diagnosis == "split" else None
        return core.diagnosis_input(top, self.snap, comparison)


def build(case: Mapping[str, Any]) -> World:
    n = case.get("members", 3)
    members = tuple(Member(user_id=f"u{i}", alias=f"m{i}", joined_at=JOINED) for i in range(1, n + 1))
    dday = case.get("dday", 30)
    start = TODAY + timedelta(days=dday)
    pins, names, facts = [], {}, {}
    for p in case["pins"]:
        live = p.get("source") == "live"
        place_id = None if live else f"place_{p['id']}"
        pins.append(Pin(pin_id=p["id"], category=p["category"], source="live" if live else "db", place_id=place_id,
                        search_query=p["name"] if live else None, created_by=p.get("by", "u1"), created_at=_ago(p["h"])))
        names[p["id"]] = p["name"]
        if place_id and p.get("facts"):
            facts[place_id] = dict(p["facts"])
    pin_category = {p.pin_id: p.category for p in pins}
    alias = {m.user_id: m.alias for m in members}
    reactions, reasons, lines = [], [], {}
    for r in case.get("reactions", []):
        at = _ago(r["h"])
        reactions.append(Reaction(reaction_id=r["id"], pin_id=r["pin"], user_id=r["by"], type=r["type"], updated_at=at))
        chips = tuple(Chip(chip_id=c, label=CHIPS[c][0], fact_key=CHIPS[c][1], wants=CHIPS[c][2]) for c in r.get("chips", []))
        if r.get("text") or chips:
            reasons.append(Reason(reaction_id=r["id"], pin_id=r["pin"], category=pin_category[r["pin"]],
                                  alias=alias[r["by"]], type=r["type"], text=r.get("text"), chips=chips,
                                  updated_at=at, pin_deleted=False))
            lines[r["id"]] = list(r.get("lines", []))
    shortlist = tuple(ShortlistItem(pin_id=i["pin"], added_by=i.get("by", "u1"), added_at=_ago(i["h"]))
                      for i in case.get("shortlist", []))
    snap = Snapshot(
        map=MapInfo(map_id="map_eval", start_date=start, end_date=start + timedelta(days=2), deleted=False),
        today=TODAY, members=members, pins=tuple(pins), reactions=tuple(reactions), reasons=tuple(reasons),
        shortlist=shortlist, last_run_at={}, actions=derive_actions(tuple(pins), tuple(reactions), shortlist),
    )
    dismissed = tuple(
        core.PastSuggestion(id=f"old{i}", diagnosis=d["diagnosis"], category=d.get("category"), fingerprint=f"fp-old-{i}",
                            status="dismissed", created_at=_ago(d["h"] + 1), resolved_at=_ago(d["h"]))
        for i, d in enumerate(case.get("dismissals", []))
    )
    return World(case=dict(case), snap=snap, names=names, lines=lines, facts=facts,
                 history=core.History(suggestions=tuple(sorted(dismissed, key=lambda s: s.created_at, reverse=True))))


# ---------------------------------------------------------------- 도구 (agent/tools.py와 같은 결과 모양)

NOT_FOUND = {"error": "NOT_FOUND"}


@dataclass
class FixtureTools:
    """진단 한 번의 도구 창구. llm.agent_diagnose의 tool_runner로 넘긴다. results는 검증(tool_result claim)에 쓴다."""
    world: World
    allowed: tuple[str, ...]
    calls: list[dict[str, Any]] = field(default_factory=list)
    results: dict[str, Any] = field(default_factory=dict)

    def run(self, call_id: str, name: str, args: Mapping[str, Any]) -> Any:
        fn = getattr(self, f"_{name}", None) if name in self.allowed else None
        result = NOT_FOUND if fn is None else fn(args)
        self.results[call_id] = result
        self.calls.append({"call_id": call_id, "name": name, "args": dict(args)})
        return result

    @property
    def _snap(self) -> Snapshot:
        return self.world.snap

    def _get_map_overview(self, args):
        s = self._snap
        times = s.action_times
        return {
            "dday": (s.map.start_date - s.today).days, "member_count": s.member_count,
            "categories": [{"category": c, "pins": sum(p.category == c for p in s.pins),
                            "confirmed": sum(s.pin(i.pin_id).category == c for i in s.shortlist)}
                           for c in categories.pinnable()],
            "last_activity_at": max(times).isoformat() if times else None,
        }

    def _get_reasons(self, args):
        category = args.get("category")
        if category is not None and category not in categories.pinnable():
            return NOT_FOUND
        pin_ids, types = set(args.get("pin_ids") or ()), set(args.get("types") or ())
        rows = [r for r in self._snap.reasons
                if (category is None or r.category == category) and (not pin_ids or r.pin_id in pin_ids)
                and (not types or r.type in types)]
        rows.sort(key=lambda r: (r.updated_at, r.reaction_id), reverse=True)
        reasons = [{
            "reaction_id": r.reaction_id, "pin_id": r.pin_id, "category": r.category, "type": r.type, "text": r.text,
            "chips": [{"chip_id": c.chip_id, "label": c.label, "fact_key": c.fact_key, "wants": c.wants} for c in r.chips],
            "member_alias": r.alias, "updated_at": r.updated_at.isoformat(),
        } for r in rows]
        return {"reasons": reasons, "total": len(reasons)}

    def _structure_reasons(self, args):
        wanted = list(dict.fromkeys(args.get("reaction_ids") or ()))
        known = {r.reaction_id for r in self._snap.reasons}
        return {"reasons": self.world.structured([i for i in wanted if i in known]), "total": sum(i in known for i in wanted),
                "not_found": [i for i in wanted if i not in known]}

    def _compare_reasons(self, args):
        pin_id, category = args.get("pin_id"), args.get("category")
        if pin_id is not None and self._snap.pin(pin_id) is not None:
            result = self.world.comparison(pin_id)
        elif category in categories.pinnable():
            result = core.compare_reasons(self.world.structured(
                [r.reaction_id for r in self._snap.reasons if r.category == category]))
        else:
            return NOT_FOUND
        return {"pin_id": pin_id, "category": category, "conflict_type": result["conflict_type"],
                "keys": result["keys"], "total": len(result["keys"])}

    def _get_place_facts(self, args):
        on_map = {p.place_id for p in self._snap.pins if p.place_id}
        wanted = list(dict.fromkeys(args.get("place_ids") or ()))
        keys = list(dict.fromkeys(args.get("fact_keys") or ()))
        rows = []
        for pid in (p for p in wanted if p in on_map):
            labels = self.world.facts.get(pid, {})
            for k in keys or sorted(labels):
                known = k in labels and labels[k] is not None
                rows.append({"place_id": pid, "fact_key": k, "value": labels.get(k) if known else None,
                             "confidence": "known" if known else "unknown"})
        return {"facts": rows, "total": len(rows), "not_found": [p for p in wanted if p not in on_map]}

    def _get_readiness(self, args):
        category = args.get("category")
        if category not in categories.recommendable():
            return NOT_FOUND
        answered = len({r.pin_id for r in self._snap.reactions if self._snap.pin(r.pin_id).category == category})
        return {"category": category, "ready": answered >= 1, "answered_count": answered, "required_count": 1}

    def _get_reaction_matrix(self, args):
        category = args.get("category")
        if category not in categories.pinnable():
            return NOT_FOUND
        s = self._snap
        members = [m.alias for m in s.members]
        alias = {m.user_id: m.alias for m in s.members}
        pins = []
        for p in (p for p in s.pins if p.category == category):
            by = {alias[r.user_id]: r.type for r in s.reactions_of(p.pin_id)}
            pins.append({"pin_id": p.pin_id, "name": self.world.names.get(p.pin_id),
                         "reactions": {a: by.get(a) for a in members}})
        return {"category": category, "members": members, "pins": pins, "total": len(pins)}


def verify(world: World, key: str, out: Any, tools: FixtureTools) -> core.Verified:
    top = world.find(key)
    comparison = world.comparison(top.pin_id) if top.diagnosis == "split" else None
    names = MEMBER_NAMES[:world.snap.member_count]
    return core.verify_diagnosis(out, top, world.snap, tools.results, member_names=names, comparison=comparison)
