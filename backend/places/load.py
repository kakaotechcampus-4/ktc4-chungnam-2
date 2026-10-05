"""자체 장소 DB 적재 스크립트 (#189). 사용법:

    python -m places.load permit  --file 서울_일반음식점.csv [--crs EPSG:5174] [--encoding cp949] [--dry-run]
    python -m places.load tourapi --file tourapi_items.json [--dry-run]
    python -m places.load labels  --file labels.csv [--constraints ../docs/constraints.md] [--dry-run]
    python -m places.load restaurants --file restaurant_seoul_curated.csv [--labels restaurant_seoul_curated_labels.json]
                                      [--exclude-bars] [--constraints ...] [--dry-run]
    python -m places.load cafes   --file cafe_seoul_curated.csv [--labels cafe_seoul_curated_labels.json|.csv]
                                  [--constraints ...] [--dry-run]
    python -m places.load restaurant-labels --file restaurant_seoul_curated_labels.json [--constraints ...] [--dry-run]

- 서울만. 인허가는 폐업을 새로 넣지 않고(이미 있는 장소가 폐업으로 바뀌면 status만 갱신), 좌표가 없는 행·업태
  대응표에 없는 행은 건너뛴다. 건너뛴 이유는 건수로 보고한다.
- 멱등이다 — 같은 파일을 다시 올려도 (source, source_id) / (place_id, fact_key)로 upsert한다.
- 실제 공공데이터 파일은 저장소에 커밋하지 않는다(.gitignore의 data/ 아래에 둔다). 카카오 응답은 다루지 않는다.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Callable, Iterator

from sqlalchemy.orm import Session

from places import ingest, repository

_ENCODINGS = ("utf-8-sig", "cp949")   # 인허가 CSV는 cp949(EUC-KR)인 경우가 많다
DEFAULT_CONSTRAINTS = Path(__file__).resolve().parents[2] / "docs" / "constraints.md"


def read_csv_rows(path: Path, encoding: str | None = None) -> list[dict[str, str]]:
    last: Exception | None = None
    for enc in ([encoding] if encoding else list(_ENCODINGS)):
        try:
            with path.open(newline="", encoding=enc) as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError as exc:
            last = exc
    raise ValueError(f"{path}: 인코딩을 읽지 못했다({', '.join(_ENCODINGS)}) — --encoding으로 지정: {last}")


def load_permit(db: Session, path: Path, *, crs: str, encoding: str | None, seoul_only: bool = True) -> list[str]:
    rows, report = ingest.parse_permit_rows(read_csv_rows(path, encoding), crs=crs, seoul_only=seoul_only)
    result = repository.upsert_places(db, rows)
    return report.lines() + [
        f"DB: 신규 {result.inserted}, 갱신 {result.updated}, 폐업으로 변경 {result.closed_marked}, "
        f"폐업(신규라 적재 안 함) {result.closed_ignored}"
    ]


def load_tourapi(db: Session, path: Path, *, seoul_only: bool = True) -> list[str]:
    items = ingest.extract_tourapi_items(json.loads(path.read_text(encoding="utf-8")))
    rows, report = ingest.parse_tourapi_items(items, seoul_only=seoul_only)
    result = repository.upsert_places(db, rows)
    return report.lines() + [f"DB: 신규 {result.inserted}, 갱신 {result.updated}"]


def load_labels(db: Session, path: Path, *, constraints: Path, encoding: str | None) -> list[str]:
    allowed = ingest.allowed_fact_keys_from_constraints(constraints.read_text(encoding="utf-8"))
    if not allowed:
        raise ValueError(f"{constraints}: fact_key를 하나도 읽지 못했다 — 경로 확인")
    labels, report = ingest.parse_label_rows(read_csv_rows(path, encoding), allowed)
    result = repository.upsert_facts(db, labels)
    skipped = f"장소를 못 찾아 건너뜀 {result.place_not_found}" if result.place_not_found else "장소 못 찾음 0"
    return report.lines() + [f"DB: place_facts upsert {result.upserted}, {skipped}"]


def _read_curated_labels(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError(f"{path}: 최상위가 배열이 아니다 — 음식점 납품본 라벨 JSON이 맞는지 확인")
    return data


def _load_curated_labels(db: Session, path: Path, *, constraints: Path) -> list[str]:
    allowed = ingest.allowed_fact_keys_from_constraints(constraints.read_text(encoding="utf-8"))
    if not allowed:
        raise ValueError(f"{constraints}: fact_key를 하나도 읽지 못했다 — 경로 확인")
    labels, report = ingest.parse_label_rows(ingest.curated_labels_to_rows(_read_curated_labels(path)), allowed)
    result = repository.upsert_facts(db, labels)
    skipped = f"장소를 못 찾아 건너뜀 {result.place_not_found}" if result.place_not_found else "장소 못 찾음 0"
    return report.lines() + [f"DB: place_facts upsert {result.upserted}, {skipped}"]


def _load_label_file(db: Session, path: Path, *, constraints: Path, encoding: str | None = None) -> list[str]:
    """납품본 라벨 파일 — .json(place_id에 rest_/cafe_ 접두어)이면 납품본 JSON, 아니면 라벨 CSV(`labels` 명령과 같은 경로)."""
    if path.suffix.lower() == ".json":
        return _load_curated_labels(db, path, constraints=constraints)
    return load_labels(db, path, constraints=constraints, encoding=encoding)


def load_cafes(
    db: Session, path: Path, *, labels: Path | None, constraints: Path, encoding: str | None = None
) -> list[str]:
    """카페 납품본: 장소 CSV(분류 카페)를 먼저 넣고(같은 트랜잭션) 라벨 JSON/CSV가 주어지면 이어서 넣는다."""
    rows, report = ingest.parse_cafe_rows(read_csv_rows(path, encoding))
    result = repository.upsert_places(db, rows)
    lines = ["[장소]"] + report.lines() + [f"DB: 신규 {result.inserted}, 갱신 {result.updated}"]
    if labels is not None:
        lines += ["[라벨]"] + _load_label_file(db, labels, constraints=constraints, encoding=encoding)
    return lines


def load_restaurants(
    db: Session, path: Path, *, labels: Path | None, constraints: Path, exclude_bars: bool, encoding: str | None = None
) -> list[str]:
    """음식점 납품본: 장소 CSV를 먼저 넣고(같은 트랜잭션) 라벨 JSON이 주어지면 이어서 넣는다."""
    rows, report = ingest.parse_curated_rows(read_csv_rows(path, encoding), exclude_bars=exclude_bars)
    result = repository.upsert_places(db, rows)
    lines = ["[장소]"] + report.lines() + [f"DB: 신규 {result.inserted}, 갱신 {result.updated}"]
    if labels is not None:
        lines += ["[라벨]"] + _load_label_file(db, labels, constraints=constraints, encoding=encoding)
    return lines


def main(argv: list[str] | None = None, *, session_factory: Callable[[], Session] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m places.load", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("permit", "tourapi", "labels", "restaurants", "cafes", "restaurant-labels"):
        p = sub.add_parser(name)
        p.add_argument("--file", required=True, type=Path)
        p.add_argument("--dry-run", action="store_true", help="파일을 해석하고 DB에는 쓰지 않는다(롤백)")
        if name in ("permit", "labels", "restaurants", "cafes"):
            p.add_argument("--encoding", default=None)
        if name == "permit":
            p.add_argument("--crs", default=ingest.DEFAULT_PERMIT_CRS, help="좌표계(기본 EPSG:5174). 위경도 값은 자동으로 그대로 쓴다")
            p.add_argument("--all-regions", action="store_true", help="서울 필터를 끈다(테스트용)")
        if name in ("labels", "restaurants", "cafes", "restaurant-labels"):
            p.add_argument("--constraints", type=Path, default=DEFAULT_CONSTRAINTS)
        if name in ("restaurants", "cafes"):
            p.add_argument("--labels", type=Path, default=None, help="라벨 JSON 또는 CSV — 있으면 장소 다음에 같은 트랜잭션으로 적재")
        if name == "restaurants":
            p.add_argument("--exclude-bars", action="store_true", help="유흥·주점류(정종/대포집/소주방, 감성주점) 제외 — 루트 결정 대기")
    args = parser.parse_args(argv)

    if not args.file.is_file():
        print(f"파일이 없다: {args.file}", file=sys.stderr)
        return 2
    if session_factory is None:
        from common.database import SessionLocal

        session_factory = SessionLocal

    db = session_factory()
    try:
        if args.command == "permit":
            lines = load_permit(db, args.file, crs=args.crs, encoding=args.encoding, seoul_only=not args.all_regions)
        elif args.command == "tourapi":
            lines = load_tourapi(db, args.file)
        elif args.command == "restaurants":
            if args.labels is not None and not args.labels.is_file():
                print(f"파일이 없다: {args.labels}", file=sys.stderr)
                return 2
            lines = load_restaurants(db, args.file, labels=args.labels, constraints=args.constraints,
                                     exclude_bars=args.exclude_bars, encoding=args.encoding)
        elif args.command == "cafes":
            if args.labels is not None and not args.labels.is_file():
                print(f"파일이 없다: {args.labels}", file=sys.stderr)
                return 2
            lines = load_cafes(db, args.file, labels=args.labels, constraints=args.constraints, encoding=args.encoding)
        elif args.command == "restaurant-labels":
            lines = _load_curated_labels(db, args.file, constraints=args.constraints)
        else:
            lines = load_labels(db, args.file, constraints=args.constraints, encoding=args.encoding)
        if args.dry_run:
            db.rollback()
            lines.append("(dry-run — DB에 쓰지 않았다)")
        else:
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
