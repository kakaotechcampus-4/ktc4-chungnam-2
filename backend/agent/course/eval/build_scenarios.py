"""시연 시나리오 세트 — "사용자가 모르는 휴무를 AI가 먼저 찾아 묻는" 장면을 평가 지도에서 코드로 고른다(pivot 8절).

    cd backend && .venv/bin/python -m agent.course.eval.build_scenarios [--data agent/course/eval/data]

평가 세트(requests.json)와 별개다. 발표에서 "시연 시나리오"로 밝히고 평가 숫자에는 섞지 않는다. 규칙은 결정적이다(지도 번호 순서).
기대 흐름(expected)은 지도 원자료의 영업시간에서 **check_goals·alternative_days 코드를 쓰지 않고** 따로 계산한다 — 테스트가 코드와 맞는지 가른다.
결과(data/scenarios.json)는 장소 이름이 들어 있어 git 무시 폴더에 둔다. 요청 세트와 같은 칸이라 `eval.demo --requests`에 그대로 쓸 수 있다.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

ORDINALS = ("첫째 날", "둘째 날", "셋째 날", "넷째 날", "다섯째 날")
PLACE_LIMIT, NIGHT_LIMIT, WALK_LIMIT = 4, 3, 1        # 종류별 상한 — 합쳐 5~8개
WALK_SUFFIX = ", 부모님이랑 가서 많이 못 걸어요"


def _topic(name: str) -> str:
    """이름 뒤에 은/는을 붙인다(받침 있으면 은). 한글이 아니면 는."""
    last = name[-1]
    return f"{name}{'은' if '가' <= last <= '힣' and (ord(last) - 0xAC00) % 28 else '는'}"


def _statuses(place: Mapping[str, Any], days: Sequence[date]) -> list[str]:
    return [place["hours"][str(d.weekday())] for d in days]


def _first_open(statuses: Sequence[str], closed_index: int) -> Optional[int]:
    return next((i for i, st in enumerate(statuses) if st == "open" and i != closed_index), None)


def _closed_place(m: Mapping[str, Any], days: Sequence[date]) -> Optional[dict]:
    """시작 때 휴무를 아는 관광지 중 여행 날짜 하루만 쉬고 다른 날은 여는 곳. 첫 번째를 쓴다."""
    for p in m["places"]:
        if p["category"] != "관광지" or not p["known_at_start"]:
            continue
        st = _statuses(p, days)
        if st.count("closed") == 1 and (k := st.index("closed")) is not None and (alt := _first_open(st, k)) is not None:
            return {"place": p, "closed_index": k, "default_index": alt}
    return None


def _closed_night(m: Mapping[str, Any], days: Sequence[date]) -> Optional[dict]:
    """야경 장소가 모두 시작 때 휴무를 알려져 있고, 어느 하루는 모두 쉬고 다른 날은 하나라도 여는 지도."""
    night = [p for p in m["places"] if "night_view" in p["labels"]]
    if not night or not all(p["known_at_start"] for p in night):
        return None
    for k in range(len(days)):
        if all(_statuses(p, days)[k] == "closed" for p in night):
            alt = next((i for i in range(len(days)) if i != k and any(_statuses(p, days)[i] == "open" for p in night)), None)
            if alt is not None:
                return {"night": night, "closed_index": k, "default_index": alt}
    return None


def build_scenarios(maps: Sequence[Mapping[str, Any]]) -> list[dict]:
    out: list[dict] = []
    used: set[str] = set()
    counts = {"closed_place": 0, "closed_night": 0, "closed_place_walk": 0}

    def add(m, kind, text, gold, expected):
        used.add(m["id"])
        counts[kind] += 1
        out.append({"map_id": m["id"], "kind": kind, "request_text": text, "gold_goals": gold, "gold_unmatched": [],
                    "conflict": False, "scenario": True, "expected": expected})

    for m in maps:
        days = [date.fromisoformat(d) for d in m["days"]]
        if (c := _closed_place(m, days)) and counts["closed_place"] < PLACE_LIMIT:
            p, k, alt = c["place"], c["closed_index"], c["default_index"]
            gid = f"place_on_day:d{k + 1}:{p['alias']}"
            add(m, "closed_place", f"{_topic(p['name'])} {ORDINALS[k]}에 꼭 가고 싶어요",
                [{"kind": "place_on_day", "day": f"d{k + 1}", "places": [p["alias"]]}],
                {"reasons": ["PLACE_CLOSED_ON_DAY"], "question": "choose_day", "subject": gid,
                 "default": f"d{alt + 1}", "goal_after": f"place_on_day:d{alt + 1}:{p['alias']}"})
    for m in maps:
        if m["id"] in used or counts["closed_night"] >= NIGHT_LIMIT:
            continue
        days = [date.fromisoformat(d) for d in m["days"]]
        if c := _closed_night(m, days):
            k, alt = c["closed_index"], c["default_index"]
            add(m, "closed_night", f"{ORDINALS[k]} 저녁엔 야경으로 끝내고 싶어요", [{"kind": "night_end", "day": f"d{k + 1}", "places": []}],
                {"reasons": ["NIGHT_PLACE_CLOSED_ON_DAY"], "question": "choose_day", "subject": f"night_end:d{k + 1}",
                 "default": f"d{alt + 1}", "goal_after": f"night_end:d{alt + 1}"})
    for m in maps:
        if m["id"] in used or counts["closed_place_walk"] >= WALK_LIMIT:
            continue
        days = [date.fromisoformat(d) for d in m["days"]]
        if c := _closed_place(m, days):
            p, k, alt = c["place"], c["closed_index"], c["default_index"]
            add(m, "closed_place_walk", f"{_topic(p['name'])} {ORDINALS[k]}에 꼭 가고 싶고{WALK_SUFFIX}",
                [{"kind": "place_on_day", "day": f"d{k + 1}", "places": [p["alias"]]}, {"kind": "daily_walk_low", "day": None, "places": []}],
                {"reasons": ["PLACE_CLOSED_ON_DAY"], "question": "choose_day", "subject": f"place_on_day:d{k + 1}:{p['alias']}",
                 "default": f"d{alt + 1}", "goal_after": f"place_on_day:d{alt + 1}:{p['alias']}"})
    return out


def main(argv: Optional[Sequence[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=Path(__file__).parent / "data")
    args = ap.parse_args(argv)
    maps = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((args.data / "maps").glob("map_*.json"))]
    scenarios = build_scenarios(maps)
    (args.data / "scenarios.json").write_text(json.dumps(scenarios, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"시나리오 {len(scenarios)}개 → {args.data / 'scenarios.json'}")
    for s in scenarios:
        print(f"  {s['map_id']} {s['kind']}: {s['request_text']} → {s['expected']['reasons']} {s['expected']['subject']} 기본값 {s['expected']['default']}")


if __name__ == "__main__":
    main()
