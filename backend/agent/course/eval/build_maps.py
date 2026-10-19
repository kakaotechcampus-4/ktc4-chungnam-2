"""실제 공공데이터(zip을 푼 폴더)에서 평가 지도를 만든다. 같은 입력·같은 시드면 같은 지도가 나온다.

    cd backend && .venv/bin/python -m agent.course.eval.build_maps <데이터 폴더> [--out agent/course/eval/data] [--count 24]

데이터 폴더에는 관광지/·음식점/·카페/ 아래 파일이 있어야 한다(인수인계 4절).
결과: <out>/maps/map_NN.json(장소 이름 포함 — 로컬 전용) + <out>/summary.json(이름 없는 집계).
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional, Sequence

from agent.course.rest_days import known_weekdays, merge_sources, parse_rest_days

MONDAY_START = date(2026, 11, 2)     # 월요일 시작 — 월요일 휴관 관광지가 걸리는 지도
FRIDAY_START = date(2026, 11, 6)     # 금요일 시작 — 일요일 휴무가 걸리는 지도
REST_COLUMNS = ("tour_쉬는날", "착한가격_휴무일", "용산구관광거리_휴무일")


@dataclass(frozen=True)
class Record:
    source_id: str
    name: str
    gu: str
    category: str            # 관광지 | 음식점 | 카페
    lat: float
    lng: float
    labels: tuple[str, ...]
    hours: dict[int, str]    # 요일(월=0) → open|closed|unknown

    @property
    def hours_known(self) -> bool:
        return known_weekdays(self.hours)


def _true_labels(raw: dict[str, Any]) -> tuple[str, ...]:
    return tuple(sorted(k for k, v in raw.items() if isinstance(v, dict) and v.get("value") == "true"))


def load_tourist(path: Path) -> list[Record]:
    out = []
    for p in json.loads(path.read_text(encoding="utf-8")):
        try:
            lat, lng = float(p["mapy"]), float(p["mapx"])
        except (KeyError, ValueError):
            continue
        out.append(Record(
            f"tour:{p['place_id']}", p["title"], p.get("sigungu", ""), "관광지", lat, lng,
            _true_labels(p.get("labels", {})), parse_rest_days(p.get("info", {}).get("rest_days", "")),
        ))
    return out


def load_csv_places(path: Path, category: str) -> list[Record]:
    out = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                lat, lng = float(row["위도"]), float(row["경도"])
            except (KeyError, ValueError):
                continue
            hours = merge_sources(*(parse_rest_days(row.get(c, "")) for c in REST_COLUMNS))
            out.append(Record(f"{category}:{row['관리번호']}", row["사업장명"], row.get("자치구", ""), category, lat, lng, (), hours))
    return out


def load_all(data_dir: Path) -> list[Record]:
    return [
        *load_tourist(data_dir / "관광지" / "tourist_seoul_curated_labels.json"),
        *load_csv_places(data_dir / "음식점" / "final_restaurant_places_hotspot.csv", "음식점"),
        *load_csv_places(data_dir / "카페" / "cafe_seoul_curated.csv", "카페"),
    ]


def _closes_in(r: Record, days: Sequence[date]) -> bool:
    return any(r.hours.get(d.weekday()) == "closed" for d in days)


def build_map(idx: int, gu: str, records: Sequence[Record], rng: random.Random) -> Optional[dict[str, Any]]:
    """지도 하나. 짝수는 월요일 시작(월요일 휴관 걸림), 홀수는 금요일 시작. 3일, 2일을 번갈아."""
    start = MONDAY_START if idx % 2 == 0 else FRIDAY_START
    days = [start + timedelta(days=i) for i in range(2 + idx % 2)]
    by_cat: dict[str, list[Record]] = defaultdict(list)
    for r in records:
        by_cat[r.category].append(r)
    tour = by_cat["관광지"]
    traps = [r for r in tour if _closes_in(r, days)]
    safe = [r for r in tour if r.hours_known and not _closes_in(r, days)]
    unknown = [r for r in tour if not r.hours_known]
    if len(traps) < 2 or len(safe) < 2 or len(by_cat["음식점"]) < 3 or len(by_cat["카페"]) < 2:
        return None

    night = [r for r in safe if "night_view" in r.labels]
    chosen = (
        rng.sample(traps, 2) + rng.sample(safe, 3)
        + (rng.sample(night, 1) if night else [])
        + (rng.sample(unknown, 1) if unknown and idx % 3 == 0 else [])     # 휴무를 끝까지 모르는 곳
        + rng.sample(by_cat["음식점"], 4) + rng.sample(by_cat["카페"], 3)
    )
    seen, places = set(), []
    for r in chosen:
        if r.source_id in seen:
            continue
        seen.add(r.source_id)
        places.append(r)
    rng.shuffle(places)

    entries = [{
        "alias": f"p{i + 1}", "source_id": r.source_id, "name": r.name, "category": r.category,
        "lat": r.lat, "lng": r.lng, "labels": list(r.labels), "hours": {str(wd): s for wd, s in r.hours.items()},
        # 시작 스냅샷: 데이터에 휴무 정보가 있는 곳(읽힌 요일이 하나라도 있는 곳)은 처음부터 안다. 데이터에 없는 곳만 모른다 —
        # 서비스에서 places가 휴무를 들고 있는 상황과 같다. 조회 도구는 스냅샷이 모르는 칸을 채운다(지도에 없으면 계속 모름)
        "known_at_start": any(s != "unknown" for s in r.hours.values()),
    } for i, r in enumerate(places)]
    return {
        "id": f"map_{idx:02d}", "gu": gu, "days": [d.isoformat() for d in days], "places": entries,
        "member_constraints": [{"kind": "daily_walk_max", "value": 90, "day": None}] if idx % 4 == 3 else [],
    }


def build_all(records: Sequence[Record], count: int, seed: int = 334) -> list[dict[str, Any]]:
    by_gu: dict[str, list[Record]] = defaultdict(list)
    for r in records:
        by_gu[r.gu].append(r)
    gus = sorted(g for g, rs in by_gu.items() if g and sum(r.category == "관광지" for r in rs) >= 6)
    maps: list[dict[str, Any]] = []
    attempt = 0
    while len(maps) < count and attempt < count * 10 and gus:
        gu = gus[attempt % len(gus)]
        m = build_map(len(maps), gu, by_gu[gu], random.Random(f"{seed}:{attempt}"))
        attempt += 1
        if m:
            maps.append(m)
    return maps


def summarize(maps: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """장소 이름·구 이름 없는 집계만 — 공개해도 된다."""
    places = [p for m in maps for p in m["places"]]
    def known(p): return all(s != "unknown" for s in p["hours"].values())
    return {
        "maps": len(maps),
        "places": len(places),
        "places_per_map": [len(m["places"]) for m in maps],
        "by_category": {c: sum(p["category"] == c for p in places) for c in ("관광지", "음식점", "카페")},
        "hours_fully_known": sum(known(p) for p in places),
        "hours_known_at_start": sum(p["known_at_start"] for p in places),
        "places_with_closed_day": sum(any(s == "closed" for s in p["hours"].values()) for p in places),
        "maps_with_member_constraint": sum(bool(m["member_constraints"]) for m in maps),
    }


def main(argv: Optional[Sequence[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data_dir", type=Path)
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "data")
    ap.add_argument("--count", type=int, default=24)
    ap.add_argument("--seed", type=int, default=334)
    args = ap.parse_args(argv)

    maps = build_all(load_all(args.data_dir), args.count, args.seed)
    (args.out / "maps").mkdir(parents=True, exist_ok=True)
    for m in maps:
        (args.out / "maps" / f"{m['id']}.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = summarize(maps)
    (args.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
