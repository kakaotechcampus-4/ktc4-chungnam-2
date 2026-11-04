"""모델 도구(docs/agent-v2.md 10절). 진단 모델이 llm을 거쳐 부르는 읽기 전용 함수들이다. 추천 막힘 조언(#587)은 모델 없이
코드가 정해서(#750) 도구 창구가 없다 — flows.advise_run이 recommend.api를 직접 읽는다.

공통 규칙(10절)
- 읽기 전용이다. 각 도구는 짧은 읽기 세션을 열고 닫는다 — 모델 호출 중에는 세션을 들고 있지 않는다(12.6).
- 다른 모듈의 `api.py`를 감싸기만 한다(#113). 비공개 데이터(run, 후보, run의 근거 줄, 제외 목록)는 읽지 않는다(2절 2번).
  get_readiness가 recommend에서 받는 것도 준비 판정 숫자뿐이다.
- 구성원은 관찰 단위 별칭(m1, m2 …, 스냅샷이 매긴 것)으로만 나온다. user_id와 이름은 나가지 않는다.
- 모든 항목에 참조 id(pin_id, reaction_id, place_id, 카테고리)가 붙는다. 출력 검증(11.2 3단계)에 쓴다.
- 목록은 상위 TOOL_RESULT_MAX_ITEMS(30)개와 총계(total)로 자른다. 같은 입력이면 같은 순서다.
- 오류는 결과로 돌려준다: 허용되지 않은 도구나 없는 대상은 {"error": "NOT_FOUND"}, ②가 실패하면
  {"error": "UNAVAILABLE"}. 상한(LIMIT_EXCEEDED)은 llm이 강제한다(#532).
- 인자는 llm.prompts의 도구 설명(parameters)대로 온다(agent-v2 10절, #532). map_id는 모델이 고르지 않고 여기서 관찰 중인 지도로 채운다. 선택 칸은 null.

기록(10절, 2절 13번): `ToolContext.calls`가 agent_runs.tool_calls에 들어간다. 결과 안의 사유 글은 남기지 않고
`text_len`(글자 수)로 바꾼다 — 모델에 준 결과에는 글이 그대로 있고, 저장할 때만 바꾼다. 검증용 원래 결과는
`ToolContext.results`에 메모리로만 둔다.
"""

import logging
import time
from collections import OrderedDict
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from statistics import median
from typing import Any

from sqlalchemy.orm import Session

from agent import core
from agent.constants import TOOL_RESULT_MAX_ITEMS, TRY_IN_SCHEDULE_MAX_PINS
from agent.course import service as course_service
from agent.course.api_schemas import CourseRequest
from agent.snapshot import Snapshot
from common import categories
from common.errors import AppError
from common.kst import kst_date
from llm import api as llm_api
from maps import api as maps_api
from pins import api as pins_api
from places import api as places_api
from recommend import api as recommend_api
from shortlist import api as shortlist_api

log = logging.getLogger("pingo.agent")

NOT_FOUND = {"error": "NOT_FOUND"}
UNAVAILABLE = {"error": "UNAVAILABLE"}

ACTIVITY_DEFAULT_WINDOW = timedelta(hours=24)   # get_activity의 since가 없을 때(초안)

Structurer = Callable[[Sequence[Mapping[str, Any]]], list[list[llm_api.EvidenceLine]]]


# ---------------------------------------------------------------- ② 결과 캐시 (8.1)

class StructureCache:
    """(reaction_id, updated_at) → 그 반응 글의 ② 결과 줄 [{fact_key, wants, badge}]. 같은 글은 같은 지도 안에서 같은
    키와 방향으로 읽힌다(②는 호출마다 조금 다를 수 있다, 8.1). 글이 바뀌면 updated_at이 바뀌어 다시 부른다.

    프로세스 메모리에 둔다. 값에는 사유 글이 없다(키와 방향뿐). 오래된 것부터 지운다."""

    def __init__(self, max_items: int = 4096):
        self._data: OrderedDict[tuple[str, str], tuple[dict[str, Any], ...]] = OrderedDict()
        self._max = max_items

    def get(self, key: tuple[str, str]) -> tuple[dict[str, Any], ...] | None:
        found = self._data.get(key)
        if found is not None:
            self._data.move_to_end(key)
        return found

    def put(self, key: tuple[str, str], lines: tuple[dict[str, Any], ...]) -> None:
        self._data[key] = lines
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()


STRUCTURE_CACHE = StructureCache()


# ---------------------------------------------------------------- 실행 창구

@dataclass
class ToolContext:
    """관찰 한 번의 도구 실행 창구. `run`을 llm.agent_diagnose의 tool_runner로 넘긴다. allowed는 유형별 허용 도구
    `llm.api.DIAGNOSIS_TOOLS[유형]`(10절, #564) — 모델에는 llm이 이 목록만 보이고, 여기서 한 번 더 막는다."""
    map_id: str
    snap: Snapshot
    allowed: tuple[str, ...]
    session_factory: Callable[[], Session]
    structure: Structurer          # ②(Gateway가 고른 planner)
    now: datetime
    cache: StructureCache = STRUCTURE_CACHE
    calls: list[dict[str, Any]] = field(default_factory=list)    # agent_runs.tool_calls(사유 글 대신 글자 수)
    results: dict[str, Any] = field(default_factory=dict)        # call_id → 모델에 준 결과. 검증용, 저장하지 않는다

    def __post_init__(self):
        self.aliases = {m.user_id: m.alias for m in self.snap.members}

    def run(self, call_id: str, name: str, args: Mapping[str, Any]) -> Any:
        started = time.monotonic()
        tool = TOOLS.get(name) if name in self.allowed else None
        result = NOT_FOUND if tool is None else tool(self, args)
        _record(self, call_id, name, args, result, started)
        return result

    def read(self):
        return _read(self.session_factory)


@contextmanager
def _read(session_factory: Callable[[], Session]) -> Iterator[Session]:
    """짧은 읽기 세션. 쓰지 않으므로 롤백으로 닫는다."""
    with session_factory() as db:
        try:
            yield db
        finally:
            db.rollback()


def _record(ctx: Any, call_id: str, name: str, args: Mapping[str, Any], result: Any, started: float, **extra: Any) -> None:
    """도구 실행 한 번을 남긴다 — 검증용 원래 결과(results, 메모리)와 저장용 기록(calls, 글 대신 글자 수)."""
    ctx.results[call_id] = result
    ctx.calls.append({
        "call_id": call_id, "name": name, "args": dict(args), "result": redact(result),
        "ms": int((time.monotonic() - started) * 1000), **extra,
    })


_TEXT_OWNERS = ("reaction_id", "line_id")   # 이 칸과 함께 있는 text는 사람이 쓴 글(사유, 근거 줄)이다


def redact(result: Any) -> Any:
    """저장용 사본 — 사유 글과 근거 글(reaction_id나 line_id와 함께 있는 text)을 글자 수로 바꾼다(2절 13번). 칩 이름과 조건
    이름(label)은 코드의 고정 문구라 남긴다."""
    if isinstance(result, list):
        return [redact(v) for v in result]
    if not isinstance(result, Mapping):
        return result
    owned = any(k in result for k in _TEXT_OWNERS)
    out = {k: redact(v) for k, v in result.items() if not (owned and k == "text")}
    if owned and "text" in result:
        out["text_len"] = len(result["text"] or "")
    return out


def _iso(at: datetime | None) -> str | None:
    return at.isoformat() if at is not None else None


def _top(items: list[Any], key: str) -> dict[str, Any]:
    return {key: items[:TOOL_RESULT_MAX_ITEMS], "total": len(items)}


# ---------------------------------------------------------------- 지도와 활동

def get_map_overview(ctx: ToolContext, args: Mapping[str, Any]) -> dict[str, Any]:
    """dday, member_count, 카테고리별 핀 수와 확정 수(삭제되지 않은 핀), last_activity_at."""
    with ctx.read() as db:
        found = maps_api.get_map_for_agent(db, ctx.map_id)
        if found is None or found["deleted"]:
            return NOT_FOUND
        matrix = pins_api.list_reaction_matrix(db, map_id=ctx.map_id)
        items = shortlist_api.list_items_for_agent(db, map_id=ctx.map_id)
    alive = {p["pin_id"]: p["category"] for p in matrix}
    confirmed = [i for i in items if i["pin_id"] in alive]
    times = ([p["created_at"] for p in matrix] + [r["updated_at"] for p in matrix for r in p["reactions"]]
             + [i["added_at"] for i in confirmed])
    return {
        "dday": (found["start_date"] - kst_date(ctx.now)).days,
        "member_count": len(found["members"]),
        "categories": [
            {"category": c, "pins": sum(v == c for v in alive.values()),
             "confirmed": sum(alive[i["pin_id"]] == c for i in confirmed)}
            for c in categories.pinnable()
        ],
        "last_activity_at": _iso(max(times)) if times else None,
    }


def get_activity(ctx: ToolContext, args: Mapping[str, Any]) -> dict[str, Any]:
    """since 이후 행동(핀 생성, 반응 등록과 수정, 확정 추가) 종류별 수, 서로 다른 사람 수, 간격 중앙값(분). since가 없으면
    24시간 전. 진단 유형의 허용 목록에는 없다(10절 표에만 있다) — M2 이후 쓸 자리다."""
    since = _parse_since(args.get("since"), ctx.now)
    if since is None:
        return NOT_FOUND
    with ctx.read() as db:
        matrix = pins_api.list_reaction_matrix(db, map_id=ctx.map_id)
        items = shortlist_api.list_items_for_agent(db, map_id=ctx.map_id)
    alive = {p["pin_id"] for p in matrix}
    acts = ([("pin", p["created_by"], p["created_at"]) for p in matrix]
            + [("reaction", r["user_id"], r["updated_at"]) for p in matrix for r in p["reactions"]]
            + [("shortlist", i["added_by"], i["added_at"]) for i in items if i["pin_id"] in alive])
    recent = sorted((a for a in acts if a[2] > since), key=lambda a: a[2])
    gaps = [(b[2] - a[2]).total_seconds() / 60 for a, b in zip(recent, recent[1:])]
    return {
        "since": _iso(since),
        "counts": {kind: sum(a[0] == kind for a in recent) for kind in ("pin", "reaction", "shortlist")},
        "distinct_actors": len({a[1] for a in recent}),
        "median_gap_minutes": round(median(gaps), 1) if gaps else None,
    }


def _parse_since(value: Any, now: datetime) -> datetime | None:
    if value is None:
        return now - ACTIVITY_DEFAULT_WINDOW
    try:
        since = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return since if since.tzinfo is not None else None


# ---------------------------------------------------------------- 반응과 사유

def get_reaction_matrix(ctx: ToolContext, args: Mapping[str, Any]) -> dict[str, Any]:
    """카테고리의 핀별 반응 표. members는 별칭 목록, pins[{pin_id, name, reactions{별칭: like|against|null}}]. null은
    미확인. 이름은 db 핀이면 장소 이름, 실시간 핀이면 검색어(#382), 찾지 못하면 null."""
    category = args.get("category")
    if category not in categories.pinnable():
        return NOT_FOUND
    with ctx.read() as db:
        matrix = pins_api.list_reaction_matrix(db, map_id=ctx.map_id, category=category)
        names = places_api.get_places([p["place_id"] for p in matrix if p["source"] != "live" and p["place_id"]], db=db)
    members = [m.alias for m in ctx.snap.members]
    pins = []
    for p in matrix:
        by_alias = {ctx.aliases[r["user_id"]]: r["type"] for r in p["reactions"] if r["user_id"] in ctx.aliases}
        place = names.get(p["place_id"]) if p["source"] != "live" else None
        pins.append({
            "pin_id": p["pin_id"],
            "name": p["search_query"] if p["source"] == "live" else (place.name if place else None),
            "reactions": {alias: by_alias.get(alias) for alias in members},
        })
    return {"category": category, "members": members, **_top(pins, "pins")}


def _reasoned(ctx: ToolContext, *, category: str | None = None) -> list[dict[str, Any]]:
    """사유가 있는 반응(삭제된 핀의 사유 포함, 8절). 카테고리가 없으면 관찰 대상 카테고리 전부. 최근 것부터."""
    with ctx.read() as db:
        rows = [
            r | {"category": c}
            for c in ([category] if category else categories.pinnable())
            for r in pins_api.list_reasoned_reactions(db, map_id=ctx.map_id, category=c)
        ]
    return sorted(rows, key=lambda r: (r["updated_at"], r["reaction_id"]), reverse=True)


def get_reasons(ctx: ToolContext, args: Mapping[str, Any]) -> dict[str, Any]:
    """사유 목록 [{reaction_id, pin_id, type, text, chips, member_alias, updated_at}]. pin_ids나 category로 고르고(둘 다
    없으면 지도 전체), types로 like·against만 고를 수 있다."""
    category = args.get("category")
    if category is not None and category not in categories.pinnable():
        return NOT_FOUND
    pin_ids = set(args.get("pin_ids") or ())
    types = set(args.get("types") or ())
    rows = [
        r for r in _reasoned(ctx, category=category)
        if (not pin_ids or r["pin_id"] in pin_ids) and (not types or r["type"] in types)
    ]
    reasons = [
        {
            "reaction_id": r["reaction_id"], "pin_id": r["pin_id"], "category": r["category"], "type": r["type"],
            "text": r["reason_text"], "chips": [dict(c) for c in r["chips"]],
            "member_alias": ctx.aliases.get(r["user_id"]), "updated_at": _iso(r["updated_at"]),
        }
        for r in rows
    ]
    return _top(reasons, "reasons")


def _text_lines(ctx: ToolContext, rows: Sequence[Mapping[str, Any]]) -> dict[str, tuple[dict[str, Any], ...]]:
    """글이 있는 반응마다 ② 결과 줄 {fact_key, wants, badge} — reaction_id → 줄(8.1). 캐시에 없는 것만 한 번에 모아 ②를 부른다.
    ②의 입력은 추천이 run을 만들 때와 같은 함수(recommend.api.reason_text_inputs, #1180)로 만든다 — ♥ 글은 preferred, 🚫 글은
    required를 agent가 다시 정하지 않는다. ②가 실패하면 llm.api.PlanEvidenceFailed."""
    def key(r: Mapping[str, Any]) -> tuple[str, str]:
        return r["reaction_id"], _iso(r["updated_at"])

    pending = [r for r in rows if r["reason_text"] and ctx.cache.get(key(r)) is None]
    if pending:
        groups = ctx.structure(recommend_api.reason_text_inputs(pending))
        for r, group in zip(pending, groups, strict=True):
            ctx.cache.put(key(r), tuple(
                {"fact_key": line.fact_key, "wants": line.wants, "badge": line.badge} for line in group
            ))
    return {r["reaction_id"]: ctx.cache.get(key(r)) or () for r in rows if r["reason_text"]}


def _lines(ctx: ToolContext, rows: Sequence[Mapping[str, Any]]) -> list[list[dict[str, Any]]]:
    """반응마다 근거 줄 [{fact_key, wants, badge, source, …}] (8.1). 글은 ②로(_text_lines — 캐시에 없을 때만, 한 번에 모아서,
    입력은 recommend.api.reason_text_inputs), 칩은 칩 표 그대로. 칩은 🚫에만 있어 required.
    글 줄과 칩 줄을 합친 뒤 추천과 같은 #422 규칙(🚫 사유 안의 음식 종류 "원함"은 preferred)을 recommend.api로 건다(#564).
    줄마다 출처(source: text|chip)를 붙이고 칩 줄에는 chip_id와 label(칩 표의 고정 이름)도 붙인다 — 요약의 키 없는 사유
    나누기(8절)가 쓴다. enforced와 not_enforced_reason은 recommend.api.evidence_line_uses가 붙인다(#740). ②가 실패하면 llm.api.PlanEvidenceFailed가 그대로 올라간다."""
    texts = _text_lines(ctx, rows)
    out = []
    for r in rows:
        lines = [dict(line, source="text") for line in texts[r["reaction_id"]]] if r["reason_text"] else []
        lines += [{"fact_key": c["fact_key"], "wants": c["wants"], "badge": "required", "source": "chip",
                   "chip_id": c["chip_id"], "label": c["label"]} for c in r["chips"]]
        out.append(recommend_api.demote_wanted_place_identity(r["category"], lines))
    return _with_use(ctx, rows, out)


def _with_use(
    ctx: ToolContext, rows: Sequence[Mapping[str, Any]], grouped: list[list[dict[str, Any]]],
) -> list[list[dict[str, Any]]]:
    """줄마다 enforced와 not_enforced_reason을 붙인다. 쓰이는지는 recommend가 정하고(#740) agent는 그 값을 쓴다."""
    with ctx.read() as db:
        for r, lines in zip(rows, grouped, strict=True):
            uses = recommend_api.evidence_line_uses(db, map_id=ctx.map_id, category=r["category"], lines=lines)
            for line, use in zip(lines, uses, strict=True):
                line.update(use)
    return grouped


_LINE_KEYS = ("fact_key", "wants", "badge")   # structure_reasons 도구가 모델에 주는 줄의 칸


def _structured(ctx: ToolContext, rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """structure_reasons와 compare_reasons의 모양 — 반응마다 {reaction_id, type, lines[{fact_key, wants, badge}]}."""
    return [
        {"reaction_id": r["reaction_id"], "type": r["type"],
         "lines": [{k: line[k] for k in _LINE_KEYS} for line in lines]}
        for r, lines in zip(rows, _lines(ctx, rows), strict=True)
    ]


def summary_reasons(ctx: ToolContext, category: str) -> list[dict[str, Any]]:
    """우리 조건 요약(8절)의 입력 — 그 카테고리의 사유 있는 반응 전부(삭제된 핀의 사유 포함, 추천과 같은 기준)와 출처 붙은
    근거 줄. 모델 도구가 아니라 상위 30개로 자르지 않는다. [{reaction_id, member, text, lines}]. member(user_id)와
    text는 core.summarize_reasons가 사람 수와 알러지 낱말을 보는 데만 쓰고 저장하지 않는다. ②가 실패하면
    PlanEvidenceFailed."""
    rows = _reasoned(ctx, category=category)
    return [
        {"reaction_id": r["reaction_id"], "member": r["user_id"], "text": r["reason_text"], "lines": lines}
        for r, lines in zip(rows, _lines(ctx, rows), strict=True)
    ]


def reasons_of(ctx: ToolContext, reaction_ids: Sequence[str]) -> list[dict[str, Any]]:
    """그 반응들의 구조화 결과 [{reaction_id, type, lines[{fact_key, wants, badge}]}] — 우리 데이터 확인(6.6)이 정체 신호의 🚫
    사유에서 키를 고를 때 쓴다. 모델 도구가 아니라 기록(calls)에 남지 않고 상위 30개로 자르지 않는다. 같은 글의 ②는 캐시로
    한 번만 부른다. ②가 실패하면 PlanEvidenceFailed."""
    wanted = set(reaction_ids)
    return _structured(ctx, [r for r in _reasoned(ctx) if r["reaction_id"] in wanted])


def structure_reasons(ctx: ToolContext, args: Mapping[str, Any]) -> dict[str, Any]:
    """[{reaction_id, type, lines[{fact_key 또는 null, wants 또는 null, badge}]}]. 글은 ②, 칩은 칩 표 그대로(8.1).
    이 지도에 없는 반응 id는 not_found로 돌려준다."""
    wanted = list(dict.fromkeys(args.get("reaction_ids") or ()))
    by_id = {r["reaction_id"]: r for r in _reasoned(ctx)}
    found = [by_id[i] for i in wanted if i in by_id]
    try:
        reasons = _structured(ctx, found[:TOOL_RESULT_MAX_ITEMS])
    except llm_api.PlanEvidenceFailed:
        return UNAVAILABLE
    return {"reasons": reasons, "total": len(found), "not_found": [i for i in wanted if i not in by_id]}


def comparison(ctx: ToolContext, *, pin_id: str | None = None, category: str | None = None) -> dict[str, Any] | None:
    """compare_reasons의 계산 — 진단 입력(split)과 도구가 같이 쓴다. pin_id면 그 핀의 사유, 아니면 카테고리의 사유.
    대상이 없으면 None. ②가 실패하면 PlanEvidenceFailed."""
    if pin_id is not None:
        rows = [r for r in _reasoned(ctx) if r["pin_id"] == pin_id]
    elif category in categories.pinnable():
        rows = _reasoned(ctx, category=category)
    else:
        return None
    return core.compare_reasons(_structured(ctx, rows[:TOOL_RESULT_MAX_ITEMS]))


PREVIEW_CALL_ID = "p1"   # 미리 돌려 보기의 도구 기록 번호(6.7). llm이 매기는 t1, t2 …와 겹치지 않는다


def preview(ctx: ToolContext, *, category: str | None, with_keys: Sequence[str] = ()) -> dict[str, Any] | None:
    """미리 돌려 보기(6.7, #1180) — 진단 전에 코드가 부른다. 그 카테고리의 사유 있는 반응 전부(삭제된 핀 포함, 추천과 같은
    기준)의 ② 결과를 모아 recommend.api.preview_filter로 실격 조건까지 남는 수를 센다. 줄 조립과 거르기는 recommend가 한다.

    결과 `{passed_count, funnel}`, with_keys가 있으면 `with_keys_count`와 `with_labels`(키의 표시 이름)도. 도구 기록에 p1로
    남긴다(모델이 고르지 않아 도구 상한에 세지 않는다, 6.3 비교와 같은 취급) — 모델은 수를 ToolClaim(call_id="p1")으로 가리킨다.
    run, 후보, 제외 목록은 다루지 않고 장소 이름과 id도 받지 않는다(2절 2번). ②가 실패하거나(UNAVAILABLE) 추천 대상이 아니거나
    추천 준비가 안 됐으면 None — 기록하지 않고, 진단은 미리 돌려 보기 없이 간다."""
    started = time.monotonic()
    if category not in categories.recommendable():
        return None
    rows = _reasoned(ctx, category=category)
    try:
        texts = _text_lines(ctx, rows)
    except llm_api.PlanEvidenceFailed:
        log.warning("agent 미리 돌려 보기 건너뜀(②) map_id=%s", ctx.map_id)
        return None
    keys = list(dict.fromkeys(with_keys))
    try:
        with ctx.read() as db:
            found = recommend_api.preview_filter(
                db, map_id=ctx.map_id, category=category, text_lines={rid: list(lines) for rid, lines in texts.items()},
                with_keys=keys,
            )
    except (AppError, ValueError) as exc:   # 준비 안 됨, 그 사이 새 글 반응(② 결과 없음) — 다음 관찰에서 다시 본다
        log.warning("agent 미리 돌려 보기 건너뜀 map_id=%s error=%s", ctx.map_id, type(exc).__name__)
        return None
    result: dict[str, Any] = {"passed_count": found["passed_count"]}
    if keys:
        labels = recommend_api.fact_labels()
        result |= {"with_keys_count": found["with_keys_count"], "with_labels": [labels[k] for k in keys if k in labels]}
    result["funnel"] = found["funnel"]
    _record(ctx, PREVIEW_CALL_ID, "preview_filter", {"category": category, "with_keys": keys}, result, started)
    return result


def record_followup_check(ctx: ToolContext, followup_of: str, result: dict[str, Any]) -> None:
    """후속 확인(6.9, #1346)을 코드 호출 기록 f1(followup_check)로 남긴다 — 결과는 수락 뒤 지난 분과 그 카테고리 새 핀 수뿐이다
    (core.followup_check_result). 모델이 고르지 않아 도구 상한에 세지 않고(p1과 같은 취급), 모델은 ToolClaim(call_id="f1")으로만 쓴다."""
    _record(ctx, core.FOLLOWUP_CALL_ID, "followup_check", {"followup_of": followup_of}, result, time.monotonic())


WEB_CHECK_CALL_PREFIX = "w"   # 웹 확인의 도구 기록 번호 w1, w2(6.8, #1216, #1317). 모델이 고르지 않아 도구 상한에 세지 않는다(p1과 같은 취급)


def record_web_check(
    ctx: ToolContext, n: int, *, pin_id: str, fact_key: str, result: dict[str, Any], started: float,
) -> None:
    """웹 확인 한 번을 도구 기록 w{n}으로 남긴다 — 인자는 pin_id·fact_key, 결과는 status와 문장 수만(core.web_tool_record). 문장,
    URL, 장소 이름은 남기지 않는다. 확인 자체는 flows가 llm을 불러 한다(진단 도구가 아니다)."""
    _record(ctx, f"{WEB_CHECK_CALL_PREFIX}{n}", "web_check", {"pin_id": pin_id, "fact_key": fact_key}, result, started)


def compare_reasons(ctx: ToolContext, args: Mapping[str, Any]) -> dict[str, Any]:
    """♥ 쪽과 🚫 쪽 사유를 키별로 모은 결과와 충돌 종류(6.3, 코드 계산). keys[{fact_key, want[], avoid[]}]의 항목은
    {reaction_id, side}."""
    pin_id, category = args.get("pin_id"), args.get("category")
    try:
        result = comparison(ctx, pin_id=pin_id, category=category)
    except llm_api.PlanEvidenceFailed:
        return UNAVAILABLE
    if result is None:
        return NOT_FOUND
    return {"pin_id": pin_id, "category": category, "conflict_type": result["conflict_type"],
            **_top(result["keys"], "keys")}


# ---------------------------------------------------------------- 장소와 추천 준비

def get_place_facts(ctx: ToolContext, args: Mapping[str, Any]) -> dict[str, Any]:
    """[{place_id, fact_key, value 또는 null, confidence}]. 이 지도 핀의 장소만 본다(실시간 핀은 place_id가 없어 대상이
    아니다). fact_keys를 줬는데 라벨이 없으면 모름(value null, unknown)으로 돌려준다 — 값을 지어내지 않는다."""
    on_map = {p.place_id for p in ctx.snap.pins if p.place_id}
    wanted = list(dict.fromkeys(args.get("place_ids") or ()))
    place_ids = [pid for pid in wanted if pid in on_map][:TOOL_RESULT_MAX_ITEMS]
    keys = list(dict.fromkeys(args.get("fact_keys") or ()))
    with ctx.read() as db:
        facts = places_api.get_facts(place_ids, db=db) if place_ids else {}
    rows = []
    for pid in place_ids:
        labels = {f.fact_key: f for f in facts.get(pid, [])}
        for k in keys or sorted(labels):
            f = labels.get(k)
            rows.append({"place_id": pid, "fact_key": k, "value": f.value if f else None,
                         "confidence": f.confidence if f else "unknown"})
    return {**_top(rows, "facts"), "not_found": [pid for pid in wanted if pid not in on_map]}


def get_readiness(ctx: ToolContext, args: Mapping[str, Any]) -> dict[str, Any]:
    """{category, ready, answered_count, required_count} — recommend.api.get_readiness 그대로(#530). 추천 대상이 아닌
    카테고리는 NOT_FOUND."""
    category = args.get("category")
    if category not in categories.recommendable():
        return NOT_FOUND
    with ctx.read() as db:
        found = recommend_api.get_readiness(db, map_id=ctx.map_id, category=category)
    return {"category": category, "ready": found["ready"], "answered_count": found["answered_count"],
            "required_count": found["required_count"]}


# ---------------------------------------------------------------- AI 코스 엔진 (6.10, #1356)

def try_in_schedule(ctx: ToolContext, args: Mapping[str, Any]) -> dict[str, Any]:
    """미확정 핀(많아야 TRY_IN_SCHEDULE_MAX_PINS개, 넘으면 앞에서 자른다)을 확정 일정에 끼워 본다 — pins[{pin_id, day, added_minutes,
    nearest_minutes, open, fills_gap}] 또는 핀마다 {pin_id, no_coords}. 계산은 core.schedule_fits(자리와 이동은 AI 코스와 같은 함수)다.

    입력은 AI 코스의 일정 입력이다: agent.course.service.read_snapshot(확정 핀과 일정), read_pins(이 핀들을 미배정으로), build_input. 영업은
    places.api(get_week_open_status, 여행 기간은 get_open_status_on_weekdays) 한 곳이다(#747). 장소 이름은 돌려주지 않는다 — 모델은
    pin_id로 가리킨다. 지도에 없거나 이미 확정한 핀은 not_found다. AI 코스를 돌리지 않는다(모델·크레딧 없음)."""
    wanted = list(dict.fromkeys(args.get("pin_ids") or ()))
    open_ids = [pid for pid in wanted if ctx.snap.pin(pid) is not None and not ctx.snap.is_confirmed(pid)]
    pin_ids = open_ids[:TRY_IN_SCHEDULE_MAX_PINS]
    with ctx.read() as db:
        found = course_service.read_snapshot(db, ctx.map_id)
        if found is None:
            return NOT_FOUND
        candidates = course_service.read_pins(db, ctx.map_id, pin_ids)
        build = course_service.build_input(replace(found, pins=found.pins + candidates), CourseRequest())
        days = course_service.trip_days(found.start_date, found.end_date)
        routable = [p.place_id for p in (*found.pins, *candidates) if p.routable]
        week = places_api.get_week_open_status(routable, db=db) if routable else {}
        asked = [c.place_id for c in candidates if c.routable]
        trip_open = places_api.get_open_status_on_weekdays(asked, sorted({d.weekday() for d in days}), db=db) if asked else {}
    confirmed_categories = {p.category for p in ctx.snap.pins if ctx.snap.is_confirmed(p.pin_id)}
    rows = core.schedule_fits(build, candidates, week, trip_open, confirmed_categories)
    return {"pins": rows, "total": len(rows), "not_found": [pid for pid in wanted if pid not in open_ids]}


TOOLS: dict[str, Callable[[ToolContext, Mapping[str, Any]], Any]] = {
    "get_map_overview": get_map_overview,
    "get_activity": get_activity,
    "get_reaction_matrix": get_reaction_matrix,
    "get_reasons": get_reasons,
    "structure_reasons": structure_reasons,
    "compare_reasons": compare_reasons,
    "get_place_facts": get_place_facts,
    "get_readiness": get_readiness,
    core.TRY_IN_SCHEDULE: try_in_schedule,
}
