"""자체 장소 DB 적재 스크립트 (#189). 사용법:

    python -m places.load permit  --file 서울_일반음식점.csv [--crs EPSG:5174] [--encoding cp949] [--dry-run]
    python -m places.load tourapi --file tourapi_items.json [--dry-run]
    python -m places.load labels  --file labels.csv [--constraints ../docs/constraints.md] [--dry-run]

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


def main(argv: list[str] | None = None, *, session_factory: Callable[[], Session] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m places.load", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("permit", "tourapi", "labels"):
        p = sub.add_parser(name)
        p.add_argument("--file", required=True, type=Path)
        p.add_argument("--dry-run", action="store_true", help="파일을 해석하고 DB에는 쓰지 않는다(롤백)")
        if name != "tourapi":
            p.add_argument("--encoding", default=None)
        if name == "permit":
            p.add_argument("--crs", default=ingest.DEFAULT_PERMIT_CRS, help="좌표계(기본 EPSG:5174). 위경도 값은 자동으로 그대로 쓴다")
            p.add_argument("--all-regions", action="store_true", help="서울 필터를 끈다(테스트용)")
        if name == "labels":
            p.add_argument("--constraints", type=Path, default=DEFAULT_CONSTRAINTS)
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
