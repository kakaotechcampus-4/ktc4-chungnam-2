"""개입 적절성 라벨링 표본 명령(#1072). 사용법:

    cd backend
    python -m agent.label_sample                          # 유형마다 25건, 홈 폴더에 CSV
    python -m agent.label_sample --per-type 40 --seed 3 --out C:/labels/agent.csv
    python -m agent.label_sample --out - > labels.csv     # CSV를 표준 출력으로(안내 문구는 표준 오류로)

서버의 스테이징 컨테이너에서(명세 21.5 「표본 자리」, #1072 후속):

    docker compose exec -T api-staging python -m agent.label_sample --staging --out - > /tmp/agent-labels.csv

  서버 브라우저 터미널(SSM)에서는 파일을 받기 어려워 표준 출력으로 낸다. 화면에서 복사하거나 위처럼 리다이렉트로 저장한다.

agent_suggestions(그 제안을 낸 agent_runs 행이 남은 것)에서 유형(stall, split, no_reaction, category_gap)마다 표본을
뽑아 사람이 「개입할 만했나」를 적을 CSV를 쓴다. 라벨 칸과 메모 칸은 비워 둔다. 판정 기준은 docs/agent-v2.md 21절.

- 대상은 로컬 개발 DB(backend/.env의 DATABASE_URL)와 스테이징 DB다. 호스트가 localhost가 아니면 읽지 않고 끝난다(종료
  코드 2). 예외는 `--staging`이고 PINGO_ENV가 staging일 때 하나다(스테이징 컨테이너 안). 그 밖의 환경(prod 포함)에서
  `--staging`을 주면 DB가 어디든 거부한다(종료 코드 2). 운영 DB에서는 돌리지 않는다(#53).
- CSV는 저장소 밖에만 쓴다. 저장소 안 경로를 주면 쓰지 않고 끝난다(종료 코드 2). 커밋하지 않는다. 이 검사는 저장소가 실제로
  있을 때(REPO_ROOT 아래 .git이 있을 때)만 한다 — 이미지 안에서는 이 파일이 /app/agent/label_sample.py라 REPO_ROOT가 /가
  되고 .git이 없다.
- 사유 원문과 구성원 이름을 넣지 않는다(명세 2절 11, 13번). 이 명령은 agent 테이블만 읽고 pins와 auth를 읽지 않는다.
  제안 문장은 화면과 같은 렌더(core.render_segments)를 거치되 구성원 글 자리는 자리 표시로 바꾼다 — 인용 조각은
  「[인용]」, 핀 조각은 「[핀]」(실시간 핀의 이름은 사용자가 친 검색어다, #382). 에이전트가 만든 text 조각만 그대로 나간다.
- 신호 특징값은 그 관찰(agent_runs.signals)에서 제안과 fingerprint가 같은 신호의 features다. 사유 글이 없다(signal_record).
"""

import argparse
import csv
import json
import random
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from agent import core
from agent.models import DIAGNOSES, AgentRun, AgentSuggestion

QUOTE_MARK = "[인용]"   # 인용 조각(구성원이 쓴 사유 글) 자리
PIN_MARK = "[핀]"        # 핀 조각(장소 이름 또는 실시간 핀의 검색어) 자리
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
BOM = "\ufeff"   # 표준 출력 앞에 붙여 리다이렉트한 파일도 엑셀에서 UTF-8로 열리게
REPO_ROOT = Path(__file__).resolve().parents[2]
HEADER = ("run_id", "diagnosis", "category", "신호 특징값", "제안 문장", "버튼", "개입할 만했나", "메모")


@dataclass(frozen=True)
class Sampled:
    """표본 한 건 — 제안 행에서 CSV에 필요한 칸만 옮긴 것."""
    run_id: str
    diagnosis: str
    category: str | None
    created_at: datetime
    title: str
    claims: list[dict[str, Any]]
    advice: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    features: dict[str, Any] | None


# ---------------------------------------------------------------- 순수 함수

def signal_features(signals: Sequence[Mapping[str, Any]], fingerprint: str) -> dict[str, Any] | None:
    """그 관찰의 신호 중 제안과 fingerprint가 같은 것의 features. 없으면 None."""
    return next((dict(s.get("features") or {}) for s in signals if s.get("fingerprint") == fingerprint), None)


def masked_refs(claims: Sequence[Mapping[str, Any]]) -> tuple[dict[str, dict[str, Any]], core.RenderRefs]:
    """구성원 글을 읽지 않고 렌더하기 위한 claim과 RenderRefs. quote claim은 자리 표시 전체를 가리키도록 범위와 다이제스트를
    바꾸고, 핀 이름은 자리 표시로 둔다. 렌더 규칙(조각 나누기, 금지 표현, 길이)은 화면과 같은 core.render_segments다."""
    by_id: dict[str, dict[str, Any]] = {}
    texts: dict[str, str] = {}
    for c in claims:
        if c.get("kind") == "quote":
            c = {**c, "start": 0, "end": len(QUOTE_MARK), "digest": core.quote_digest(QUOTE_MARK)}
            texts[c["reaction_id"]] = QUOTE_MARK
        by_id[c["id"]] = dict(c)
    pins = {pid: PIN_MARK for pid in core.referenced_pin_ids(claims)}
    return by_id, core.RenderRefs(pin_names=pins, reaction_texts=texts)


def _line_text(segments: Sequence[Any]) -> str:
    return "".join(f"「{s.text}」" if s.kind in ("quote", "pin") else s.text for s in segments)


def suggestion_text(title: str, claims: Sequence[Mapping[str, Any]], advice: Sequence[Mapping[str, Any]]) -> str:
    """제목과 확인된 것 줄. 줄은 "- "로 시작하고 짐작 줄은 끝에 (짐작)을 붙인다. 화면 렌더가 뺄 줄(금지 표현, 너무 긺)은
    "- (렌더에서 빠짐)"으로 남긴다 — 판정하는 사람이 모델이 무엇을 냈는지 알 수 있게."""
    by_id, refs = masked_refs(claims)
    head = core.render_title(title, by_id, refs) or "(제목 렌더 실패)"
    lines = [head]
    for line in advice:
        segments = core.render_segments(line["slot_text"], by_id, refs)
        body = _line_text(segments) if segments else "(렌더에서 빠짐)"
        lines.append(f"- {body}{' (짐작)' if line.get('is_guess') else ''}")
    return "\n".join(lines)


def button_labels(actions: Sequence[Mapping[str, Any]]) -> str:
    """버튼 이름은 코드 문구다(11.2 M1-2, 템플릿)."""
    return " / ".join(str(a.get("label", a.get("type", ""))) for a in actions)


def pick(rows: Sequence[Sampled], per_type: int, seed: int) -> list[Sampled]:
    """유형마다 per_type건까지 무작위로 고른다(seed로 다시 뽑아도 같다). 유형, 만든 시각 순으로 돌려준다."""
    rng = random.Random(seed)
    by_type: dict[str, list[Sampled]] = defaultdict(list)
    for r in sorted(rows, key=lambda r: (r.diagnosis, r.created_at, r.run_id)):
        by_type[r.diagnosis].append(r)
    chosen: list[Sampled] = []
    for diagnosis in DIAGNOSES:
        group = by_type.get(diagnosis, [])
        chosen += sorted(rng.sample(group, min(per_type, len(group))), key=lambda r: (r.created_at, r.run_id))
    return chosen


def csv_row(r: Sampled) -> list[str]:
    features = json.dumps(r.features, ensure_ascii=False, sort_keys=True) if r.features is not None else ""
    return [r.run_id, r.diagnosis, r.category or "", features, suggestion_text(r.title, r.claims, r.advice),
            button_labels(r.actions), "", ""]


def is_local_db(url: str) -> bool:
    return (make_url(url).host or "") in LOCAL_HOSTS


def db_refusal(url: str, *, staging: bool, environment: str) -> str | None:
    """이 DB에서 돌리지 않을 이유. 돌려도 되면 None. --staging은 PINGO_ENV가 staging일 때만 받고, 그때만 로컬이 아닌 DB를
    허용한다."""
    if staging and environment != "staging":
        return f"--staging은 PINGO_ENV=staging에서만 쓴다(지금 {environment})"
    if not staging and not is_local_db(url):
        return "DATABASE_URL이 로컬 DB가 아니다 — 로컬 개발 DB에서만 돌린다(스테이징 컨테이너 안이면 --staging)"
    return None


def inside_repo(path: Path, root: Path = REPO_ROOT) -> bool:
    """저장소 안 경로인가. 저장소가 없으면(root 아래 .git이 없으면 — 이미지 안) 검사하지 않는다."""
    return (root / ".git").exists() and path.resolve().is_relative_to(root)


# ---------------------------------------------------------------- 읽기와 쓰기

def load(db: Session) -> list[Sampled]:
    """agent_runs 행이 남은 제안(run_id가 있는 것). 30일이 지나 관찰 행이 지워진 제안은 특징값이 없어 뺀다."""
    found = db.execute(
        select(AgentSuggestion, AgentRun.signals).join(AgentRun, AgentRun.id == AgentSuggestion.run_id)
    ).all()
    return [
        Sampled(run_id=str(s.run_id), diagnosis=s.diagnosis, category=s.category, created_at=s.created_at,
                title=s.title, claims=list(s.claims), advice=list(s.advice), actions=list(s.actions),
                features=signal_features(signals, s.fingerprint))
        for s, signals in found
    ]


def _write_rows(f: TextIO, rows: Sequence[Sampled], **fmt: Any) -> None:
    out = csv.writer(f, **fmt)
    out.writerow(HEADER)
    out.writerows(csv_row(r) for r in rows)


def write_csv(path: Path | None, rows: Sequence[Sampled]) -> None:
    """엑셀에서 바로 열리게 UTF-8 BOM으로 쓴다. path가 None이면 표준 출력으로 낸다 — 리다이렉트로 저장해도 엑셀에서 열리게
    BOM을 앞에 붙이고, 줄 끝은 LF다(텍스트 출력이 줄 끝을 다시 바꾸지 않게)."""
    if path is None:
        sys.stdout.write(BOM)
        _write_rows(sys.stdout, rows, lineterminator="\n")
        sys.stdout.flush()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        _write_rows(f, rows)


def export(db: Session, path: Path | None, *, per_type: int, seed: int) -> dict[str, int]:
    """표본을 뽑아 CSV로 쓰고(path가 None이면 표준 출력) 유형별 건수를 돌려준다."""
    chosen = pick(load(db), per_type, seed)
    write_csv(path, chosen)
    counts = {d: 0 for d in DIAGNOSES}
    for r in chosen:
        counts[r.diagnosis] += 1
    return counts


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="개입 적절성 라벨링 표본 CSV(로컬 개발 DB, 스테이징은 --staging)")
    parser.add_argument("--per-type", type=int, default=25, help="유형마다 뽑을 최대 건수")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", default="", help="CSV 경로(저장소 밖). -면 표준 출력. 없으면 홈 폴더에 날짜 이름으로")
    parser.add_argument("--staging", action="store_true",
                        help="스테이징 컨테이너 안에서 스테이징 DB를 읽는다(PINGO_ENV=staging일 때만)")
    args = parser.parse_args(argv)

    # 인자 검사(--help)만으로 DB 엔진을 만들지 않는다
    from common.database import SessionLocal, engine
    from common.settings import settings

    refusal = db_refusal(engine.url.render_as_string(hide_password=True), staging=args.staging,
                         environment=settings.environment)
    if refusal is not None:
        print(refusal, file=sys.stderr)
        return 2
    to_stdout = args.out == "-"
    path = None if to_stdout else (
        Path(args.out) if args.out else Path.home() / f"agent-labels-{datetime.now():%Y%m%d-%H%M%S}.csv")
    if path is not None and inside_repo(path):
        print("CSV를 저장소 안에 쓰지 않는다 — 저장소 밖 경로를 준다", file=sys.stderr)
        return 2
    with SessionLocal() as db:
        try:
            counts = export(db, path, per_type=args.per_type, seed=args.seed)
        finally:
            db.rollback()
    info = sys.stderr if to_stdout else sys.stdout   # 표준 출력이 CSV면 안내는 표준 오류로
    print(f"저장: {'표준 출력' if to_stdout else path}", file=info)
    print(" ".join(f"{d}={n}" for d, n in counts.items()), file=info)
    return 0


if __name__ == "__main__":
    sys.exit(main())
