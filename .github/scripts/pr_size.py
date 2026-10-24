"""PR이 건드린 모듈 수와 파일 수를 센다(#731, 멘토 리뷰 #680). 결과는 PR 코멘트용 마크다운이다.

base와 head의 갈라진 지점부터 head까지(git diff base...head) 바뀐 파일을 나눈다.
- 테스트, 문서, 마이그레이션, 생성 파일은 따로 센다.
- 나머지(코드와 설정)는 모듈로 묶는다: backend/<모듈>, backend(공통 파일), frontend, contracts, .github, 기타.
  backend 모듈은 backend/pyproject.toml의 root_packages와 같은 디렉토리다.

로컬에서 push 전에 보기: python .github/scripts/pr_size.py origin/develop HEAD
"""

import re
import subprocess
import sys
from collections import Counter

MARKER = "<!-- pr-size -->"

# (종류, 경로 정규식). 위에서부터 처음 맞는 종류 하나로 센다. 어디에도 안 맞으면 코드와 설정이다.
KINDS = [
    ("마이그레이션", r"^backend/alembic/versions/"),
    ("생성 파일", r"^contracts/src/types/api\.d\.ts$"),
    ("테스트", r"(^|/)tests?/|^backend/integration/|(^|/)conftest\.py$|\.test\.[jt]sx?$|^qa/"),
    ("문서", r"^docs/|\.md$"),
]
TOP_MODULES = {"frontend", "contracts", ".github"}


def changed_files(base: str, head: str) -> list[str]:
    out = subprocess.run(
        ["git", "-c", "core.quotepath=false", "diff", "--name-only", "-z", f"{base}...{head}"],
        check=True, capture_output=True,
    ).stdout.decode("utf-8")
    return [path for path in out.split("\0") if path]


def kind_of(path: str) -> str | None:
    return next((kind for kind, pattern in KINDS if re.search(pattern, path)), None)


def module_of(path: str) -> str:
    parts = path.split("/")
    if parts[0] == "backend":
        return f"backend/{parts[1]}" if len(parts) > 2 else "backend(공통 파일)"
    return parts[0] if parts[0] in TOP_MODULES else "기타"


def report(files: list[str]) -> str:
    kinds = Counter()
    modules = Counter()
    for path in files:
        kind = kind_of(path)
        if kind:
            kinds[kind] += 1
        else:
            modules[module_of(path)] += 1

    lines = [MARKER, "#### 이 PR이 건드린 범위", ""]
    if modules:
        lines += [f"코드와 설정: 모듈 {len(modules)}곳, 파일 {sum(modules.values())}개", "", "| 모듈 | 파일 |", "|---|---|"]
        lines += [f"| `{name}` | {count} |" for name, count in sorted(modules.items())]
    else:
        lines.append("코드와 설정: 없음")
    others = ", ".join(
        f"{kind} {kinds[kind]}개" for kind in ("테스트", "문서", "마이그레이션", "생성 파일") if kinds[kind]
    ) or "없음"
    lines += ["", f"따로 센 것: {others}", ""]
    if len(modules) > 3:
        lines.append("모듈이 세 곳을 넘었습니다. 루트 CLAUDE.md \"일하는 순서\"의 네 질문에 PR 본문에서 답해 주세요.")
        lines.append("")
    lines.append("<sub>base...head 기준. push할 때마다 이 코멘트가 고쳐집니다. 세는 규칙은 .github/scripts/pr_size.py</sub>")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("사용법: python .github/scripts/pr_size.py <base> <head>")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(report(changed_files(sys.argv[1], sys.argv[2])))
