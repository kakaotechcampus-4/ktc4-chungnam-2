"""자체 장소 DB 적재 스크립트 (#189). 사용법:

    python -m places.load permit  --file 서울_일반음식점.csv [--file ... | 디렉터리 | "글롭*.csv"] [--crs EPSG:5174] [--encoding cp949]
                                  [--all-regions] [--close-missing [--force]] [--dry-run]
    python -m places.load tourapi --file tourapi_items.json [--all-regions] [--labels labels.csv|.json] [--constraints ...] [--dry-run]
    python -m places.load labels  --file labels.csv [--constraints ../docs/constraints.md] [--dry-run]
    python -m places.load restaurants --file restaurant_seoul_curated.csv [--labels restaurant_seoul_curated_labels.json]
                                      [--exclude-bars] [--all-regions] [--constraints ...] [--dry-run]
    python -m places.load cafes   --file cafe_seoul_curated.csv [--labels cafe_seoul_curated_labels.json|.csv]
                                  [--exclude-bars] [--all-regions] [--constraints ...] [--dry-run]
    python -m places.load place-hours --file <정예 라벨 JSON | 서울 관광지 tourist_seoul_closed_days.json> [--all-regions] [--dry-run]
    python -m places.load restaurant-labels --file restaurant_seoul_curated_labels.json [--overwrite] [--constraints ...] [--dry-run]

- 정예 우선(#507): `restaurants`·`cafes`·`tourapi`에 `--authoritative`를 주면 같은 (source, source_id)의 이름·분류·주소·좌표를 파일 값으로
  갱신한다(분류가 달라도). 정예 라벨은 원래 파일 값이 같은 (장소, fact_key)를 덮는다.
  `permit`(인허가 커버리지)은 이미 있는 장소의 이름·분류·좌표를 건드리지 않고 신규 행만 넣는다. `restaurant-labels`는 기본이 커버리지용 —
  이미 있는 (장소, fact_key) 라벨을 건드리지 않고 없는 키만 넣는다(`--overwrite`면 덮는다). 적재 순서: 정예 → 커버리지.

- `place-hours`(#690): 라벨 JSON의 `info.hours`·`closed_days`·`closed_note`·`hours_note`를 `place_hours`에 넣는다(칸이 없으면 행을 안 만든다 = 모름).
  restaurants·cafes·tourapi의 라벨 적재는 `info`를 계속 읽지 않고, 이 단계가 따로 읽는다. 같은 장소는 파일 값으로 갱신하고, 파일에 없는 장소의 행은 지우지 않는다.
  장소를 못 찾으면 건수만 보고한다(장소를 먼저 적재). 항목에 `addr1`이 있고 서울이 아니면 `--all-regions` 없이는 건너뛴다.
- 기본은 서울만이다. 장소를 받는 명령(permit·tourapi·restaurants·cafes)에 `--all-regions`를 주면 서울 판정(주소 "서울", TourAPI areacode,
  서울 좌표 상자)을 모두 끈다(타 지역 적재용). 좌표가 없거나 위경도 범위 밖인 행은 그때도 건너뛴다. 보고에 지역별(시도명 앞 두 글자) 적재 수가 한 줄 붙는다.
- `permit --close-missing`(기본 꺼짐): 파일에 없는 장소를 status='closed'로 바꾼다(삭제 아님, 라벨 유지). 대상은 source='permit'·curated=false·열림뿐이다.
  파일이 여러 개로 쪼개져 있으므로 `--file`을 두 개 이상(또는 디렉터리·글롭이 두 파일 이상)으로 받아 한 번에 읽은 뒤에만 닫고, 파일 하나면 거부한다.
  파일에 다시 나온 기존 장소가 열린 인허가 장소의 30% 미만이면 실수로 보고 거부한다(`--force`로만 우회). `--dry-run`이 닫힐 건수를 먼저 보여 준다.
  닫힌 장소가 파일에 영업으로 다시 나오면 다시 연다(이름·분류·좌표는 그대로).
- 인허가는 폐업을 새로 넣지 않고(이미 있는 장소가 폐업으로 바뀌면 status만 갱신), 좌표가 없는 행·업태
  대응표에 없는 행은 건너뛴다. 건너뛴 이유는 건수로 보고한다.
- 멱등이다 — 같은 파일을 다시 올려도 (source, source_id) / (place_id, fact_key)로 upsert한다.
- 실제 공공데이터 파일은 저장소에 커밋하지 않는다(.gitignore의 data/ 아래에 둔다). 카카오 응답은 다루지 않는다.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import sys
from pathlib import Path
from typing import Callable, Iterator

from sqlalchemy.orm import Session

from places import ingest, repository
from places.scripts import recompute_can_recommend as recompute_cli

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


class CloseMissingRefused(Exception):
    """--close-missing의 안전장치가 막았다. DB에는 아무것도 쓰지 않는다."""


def load_permit(
    db: Session, path: Path | list[Path], *, crs: str, encoding: str | None, seoul_only: bool = True,
    close_missing: bool = False, force: bool = False,
) -> list[str]:
    """인허가 파일 하나 또는 여러 개. --close-missing은 여러 파일을 모두 읽은 뒤에만 닫는다(한 파일이면 CloseMissingRefused)."""
    paths = [path] if isinstance(path, Path) else list(path)
    if close_missing and len(paths) < 2:
        raise CloseMissingRefused("--close-missing은 쪼개진 인허가 파일을 모두 한 번에 줄 때만 쓴다(--file을 여러 번, 또는 디렉터리·글롭) — 파일 하나로는 닫지 않는다")
    raw = [row for p in paths for row in read_csv_rows(p, encoding)]
    rows, report = ingest.parse_permit_rows(raw, crs=crs, seoul_only=seoul_only)
    plan = None
    if close_missing:
        plan = ingest.plan_close_missing(repository.open_permit_source_ids(db), ingest.permit_source_ids(raw), force=force)
        if plan.refused:
            raise CloseMissingRefused(plan.refused)
    result = repository.upsert_places(db, rows, existing_mode="keep")   # 인허가 커버리지는 이미 있는 장소를 건드리지 않는다(#507)
    lines = (["파일 " + ", ".join(p.name for p in paths)] if len(paths) > 1 else []) + report.lines() + _place_db_lines(result) + [
        f"DB: 폐업으로 변경 {result.closed_marked}, 폐업(신규라 적재 안 함) {result.closed_ignored}"
    ]
    if plan is not None:
        closed = repository.close_permit_places(db, sorted(plan.to_close))
        lines.append(f"DB: 파일에 없어 닫음 {closed}행(닫을 수 있는 {plan.candidates}행 중 파일에 나온 것 {plan.found_in_file}행, 라벨은 그대로)")
    return lines


def expand_files(patterns: list[Path]) -> list[Path]:
    """--file 값을 파일 목록으로 푼다 — 파일, 디렉터리(안의 *.csv), 글롭(*?[ 포함)을 받는다. 중복은 한 번만, 없으면 FileNotFoundError."""
    out: list[Path] = []
    for pattern in patterns:
        if pattern.is_dir():
            found = sorted(pattern.glob("*.csv"))
        elif any(ch in str(pattern) for ch in "*?["):
            found = sorted(Path(m) for m in glob.glob(str(pattern)))
        else:
            found = [pattern]
        if not found or not all(f.is_file() for f in found):
            raise FileNotFoundError(f"파일이 없다: {pattern}")
        out += [f for f in found if f not in out]
    return out


def _place_db_lines(result: repository.PlaceUpsertResult) -> list[str]:
    lines = [f"DB: 신규 {result.inserted}, 갱신 {result.updated}"]
    if result.updated:
        lines.append(f"  갱신 중 이름 바뀜 {result.name_changed}, 분류 바뀜 {result.category_changed}")
    if result.reopened:
        lines.append(f"  닫혀 있다가 파일에 다시 나와 되살림 {result.reopened}행")
    if result.existing_kept:
        lines.append(f"  이미 있어 건드리지 않음 {result.existing_kept}행(이름·분류·좌표 유지)")
    if result.category_kept:
        lines.append(f"  ! 다른 분류로 이미 있음 {result.category_kept}행 — 분류를 바꾸지 않고 건너뛰었다")
    return lines


def _existing_mode(authoritative: bool) -> str:
    """정예 파일(--authoritative)은 같은 (source, source_id)의 이름·분류를 파일 값으로 덮는다(#507)."""
    return "overwrite" if authoritative else "refresh"


def load_tourapi(
    db: Session, path: Path, *, seoul_only: bool = True, labels: Path | None = None, constraints: Path = DEFAULT_CONSTRAINTS,
    authoritative: bool = False,
) -> list[str]:
    """관광지·문화시설·레포츠·시장(contenttypeid 12·14·28·38). 라벨 파일이 주어지면 장소 다음에 같은 트랜잭션으로 넣는다."""
    items = ingest.extract_tourapi_items(json.loads(path.read_text(encoding="utf-8")))
    rows, report = ingest.parse_tourapi_items(items, seoul_only=seoul_only)
    result = repository.upsert_places(db, rows, existing_mode=_existing_mode(authoritative))
    lines = report.lines() + _place_db_lines(result)
    if labels is not None:
        lines = ["[장소]"] + lines + ["[라벨]"] + _load_label_file(db, labels, constraints=constraints)
    return lines


def _label_db_line(result: repository.FactUpsertResult) -> str:
    skipped = f"장소를 못 찾아 건너뜀 {result.place_not_found}" if result.place_not_found else "장소 못 찾음 0"
    kept = f", 이미 있어 건드리지 않음 {result.kept}" if result.kept else ""
    return f"DB: place_facts upsert {result.upserted}{kept}, {skipped}"


def load_labels(db: Session, path: Path, *, constraints: Path, encoding: str | None, overwrite: bool = True) -> list[str]:
    allowed = ingest.allowed_fact_keys_from_constraints(constraints.read_text(encoding="utf-8"))
    if not allowed:
        raise ValueError(f"{constraints}: fact_key를 하나도 읽지 못했다 — 경로 확인")
    labels, report = ingest.parse_label_rows(read_csv_rows(path, encoding), allowed)
    result = repository.upsert_facts(db, labels, overwrite=overwrite)
    return report.lines() + [_label_db_line(result)]


def _read_curated_labels(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError(f"{path}: 최상위가 배열이 아니다 — 음식점 납품본 라벨 JSON이 맞는지 확인")
    return data


def _load_curated_labels(db: Session, path: Path, *, constraints: Path, overwrite: bool = True) -> list[str]:
    allowed = ingest.allowed_fact_keys_from_constraints(constraints.read_text(encoding="utf-8"))
    if not allowed:
        raise ValueError(f"{constraints}: fact_key를 하나도 읽지 못했다 — 경로 확인")
    labels, report = ingest.parse_label_rows(ingest.curated_labels_to_rows(_read_curated_labels(path)), allowed)
    result = repository.upsert_facts(db, labels, overwrite=overwrite)
    return report.lines() + [_label_db_line(result)]


def _load_label_file(db: Session, path: Path, *, constraints: Path, encoding: str | None = None) -> list[str]:
    """납품본 라벨 파일 — .json(place_id에 rest_/cafe_ 접두어)이면 납품본 JSON, 아니면 라벨 CSV(`labels` 명령과 같은 경로)."""
    if path.suffix.lower() == ".json":
        return _load_curated_labels(db, path, constraints=constraints)
    return load_labels(db, path, constraints=constraints, encoding=encoding)


def load_cafes(
    db: Session, path: Path, *, labels: Path | None, constraints: Path, exclude_bars: bool = False, encoding: str | None = None,
    authoritative: bool = False, seoul_only: bool = True,
) -> list[str]:
    """카페 납품본: 장소 CSV(분류 카페)를 먼저 넣고(같은 트랜잭션) 라벨 JSON/CSV가 주어지면 이어서 넣는다."""
    rows, report = ingest.parse_cafe_rows(read_csv_rows(path, encoding), exclude_bars=exclude_bars, seoul_only=seoul_only)
    result = repository.upsert_places(db, rows, existing_mode=_existing_mode(authoritative))
    lines = ["[장소]"] + report.lines() + _place_db_lines(result)
    if labels is not None:
        lines += ["[라벨]"] + _load_label_file(db, labels, constraints=constraints, encoding=encoding)
    return lines


def load_restaurants(
    db: Session, path: Path, *, labels: Path | None, constraints: Path, exclude_bars: bool, encoding: str | None = None,
    authoritative: bool = False, seoul_only: bool = True,
) -> list[str]:
    """음식점 납품본: 장소 CSV를 먼저 넣고(같은 트랜잭션) 라벨 JSON이 주어지면 이어서 넣는다."""
    rows, report = ingest.parse_curated_rows(read_csv_rows(path, encoding), exclude_bars=exclude_bars, seoul_only=seoul_only)
    result = repository.upsert_places(db, rows, existing_mode=_existing_mode(authoritative))
    lines = ["[장소]"] + report.lines() + _place_db_lines(result)
    if labels is not None:
        lines += ["[라벨]"] + _load_label_file(db, labels, constraints=constraints, encoding=encoding)
    return lines


def load_place_hours(db: Session, path: Path, *, seoul_only: bool = True) -> list[str]:
    """영업시간·휴무일(#690) — 정예 라벨 JSON(rest_·cafe_·tour_) 또는 서울 관광지 closed_days JSON. 라벨 적재와 따로 읽는다."""
    rows, report = ingest.parse_hours_entries(_read_curated_labels(path), seoul_only=seoul_only)
    result = repository.upsert_hours(db, rows)
    skipped = f"장소를 못 찾아 건너뜀 {result.place_not_found}" if result.place_not_found else "장소 못 찾음 0"
    return report.lines() + [f"DB: place_hours upsert {result.upserted}, {skipped}"]


def main(argv: list[str] | None = None, *, session_factory: Callable[[], Session] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m places.load", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("permit", "tourapi", "labels", "restaurants", "cafes", "restaurant-labels", "place-hours"):
        p = sub.add_parser(name)
        p.add_argument("--file", required=True, type=Path, action="append" if name == "permit" else "store",
                       help="인허가 파일(여러 번 가능, 디렉터리·글롭도 받는다)" if name == "permit" else None)
        if name in ("permit", "tourapi", "restaurants", "cafes", "place-hours"):
            p.add_argument("--all-regions", action="store_true",
                           help="서울 판정(주소·areacode·좌표 상자)을 모두 끈다 — 타 지역 적재용. 좌표 없음·범위 밖은 그대로 건너뛴다")
        p.add_argument("--dry-run", action="store_true", help="파일을 해석하고 DB에는 쓰지 않는다(롤백)")
        if name in ("permit", "labels", "restaurants", "cafes"):
            p.add_argument("--encoding", default=None)
        if name == "permit":
            p.add_argument("--crs", default=ingest.DEFAULT_PERMIT_CRS, help="좌표계(기본 EPSG:5174). 위경도 값은 자동으로 그대로 쓴다")
            p.add_argument("--close-missing", action="store_true",
                           help="파일에 없는 인허가 장소(비정예·열림)를 status='closed'로 바꾼다. --file을 여러 개(또는 디렉터리·글롭)로 줄 때만")
            p.add_argument("--force", action="store_true", help="--close-missing의 '파일이 너무 적다(기존의 30% 미만)' 거부를 우회한다")
        if name in ("labels", "restaurants", "cafes", "restaurant-labels", "tourapi"):
            p.add_argument("--constraints", type=Path, default=DEFAULT_CONSTRAINTS)
        if name in ("restaurants", "cafes", "tourapi"):
            p.add_argument("--labels", type=Path, default=None, help="라벨 JSON 또는 CSV — 있으면 장소 다음에 같은 트랜잭션으로 적재")
        if name in ("restaurants", "cafes", "tourapi"):
            p.add_argument("--authoritative", action="store_true",
                           help="정예 파일 — 같은 (source, source_id)의 이름·분류·주소·좌표를 파일 값으로 갱신한다(분류가 달라도, #507). 라벨은 원래 파일 값이 이긴다")
        if name == "restaurant-labels":
            p.add_argument("--overwrite", action="store_true",
                           help="이미 있는 (장소, fact_key) 라벨도 파일 값으로 덮는다. 기본은 인허가 커버리지용 — 있는 라벨은 건드리지 않고 없는 키만 넣는다(#507)")
        if name in ("restaurants", "cafes"):
            p.add_argument("--exclude-bars", action="store_true", help="유흥·주점류(정종/대포집/소주방, 감성주점) 제외 — 루트 결정 대기")
    args = parser.parse_args(argv)

    if args.command == "permit":
        try:
            args.file = expand_files(args.file)
        except FileNotFoundError as exc:
            print(exc, file=sys.stderr)
            return 2
    elif not args.file.is_file():
        print(f"파일이 없다: {args.file}", file=sys.stderr)
        return 2
    if session_factory is None:
        from common.database import SessionLocal

        session_factory = SessionLocal

    db = session_factory()
    try:
        if args.command == "permit":
            lines = load_permit(db, args.file, crs=args.crs, encoding=args.encoding, seoul_only=not args.all_regions,
                                close_missing=args.close_missing, force=args.force)
        elif args.command == "tourapi":
            if args.labels is not None and not args.labels.is_file():
                print(f"파일이 없다: {args.labels}", file=sys.stderr)
                return 2
            lines = load_tourapi(db, args.file, labels=args.labels, constraints=args.constraints,
                                 authoritative=args.authoritative, seoul_only=not args.all_regions)
        elif args.command == "restaurants":
            if args.labels is not None and not args.labels.is_file():
                print(f"파일이 없다: {args.labels}", file=sys.stderr)
                return 2
            lines = load_restaurants(db, args.file, labels=args.labels, constraints=args.constraints,
                                     exclude_bars=args.exclude_bars, encoding=args.encoding,
                                     authoritative=args.authoritative, seoul_only=not args.all_regions)
        elif args.command == "cafes":
            if args.labels is not None and not args.labels.is_file():
                print(f"파일이 없다: {args.labels}", file=sys.stderr)
                return 2
            lines = load_cafes(db, args.file, labels=args.labels, constraints=args.constraints,
                              exclude_bars=args.exclude_bars, encoding=args.encoding,
                              authoritative=args.authoritative, seoul_only=not args.all_regions)
        elif args.command == "place-hours":
            lines = load_place_hours(db, args.file, seoul_only=not args.all_regions)
        elif args.command == "restaurant-labels":
            lines = _load_curated_labels(db, args.file, constraints=args.constraints, overwrite=args.overwrite)
        else:
            lines = load_labels(db, args.file, constraints=args.constraints, encoding=args.encoding)
        # 적재 끝에 can_recommend를 같은 트랜잭션에서 다시 계산한다(멱등, dry-run이면 같이 롤백)
        lines += recompute_cli.report_lines(repository.recompute_can_recommend(db), dry_run=False)
        if args.dry_run:
            db.rollback()
            lines.append("(dry-run — DB에 쓰지 않았다)")
        else:
            db.commit()
    except CloseMissingRefused as exc:
        db.rollback()
        print(f"거부: {exc}", file=sys.stderr)
        return 2
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
