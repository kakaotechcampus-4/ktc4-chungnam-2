"""
운영, CI, 로컬, 배포 도구의 Python과 PostgreSQL/PostGIS 버전이 같은지 (#916, 멘토 리뷰).

CI는 운영에서 돌 것을 미리 확인하는 곳이라 환경이 다르면 그 확인이 운영을 대신하지 못한다. 처음에는 CI만 Python 3.10,
PostGIS 16-3.4였다(#37에서 정한 값이 남음). 버전은 여러 파일에 적힐 수밖에 없어서, 한쪽만 올리면 이 테스트가 실패하게 한다.

- Python: `backend/.python-version`이 정본이다. CI는 이 파일을 읽고(`python-version-file`), 이미지(`backend/Dockerfile`)는 같은 값이어야 한다.
- PostGIS: CI 서비스, 로컬 compose, 배포(서버 안 DB, 백업·이전 스크립트)의 `postgis/postgis:<PG>-<PostGIS>` 태그가 모두 같고,
  운영 DB(RDS)의 버전으로 적어 둔 deploy_rules.md 「배포 구성」의 DB 줄과 메이저가 맞아야 한다.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POSTGIS_TAG = re.compile(r"postgis/postgis:(\d+-\d+\.\d+)")
POSTGIS_FILES = [
    ".github/workflows/backend-test.yml",
    "backend/docker-compose.yml",
    "deploy/compose.db.yml",
    "deploy/backup.sh",
    "deploy/move-to-rds.sh",
    "deploy/rds-setup.sh",
]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _python_version() -> str:
    return _read("backend/.python-version").strip()


def test_ci_reads_the_python_version_file():
    workflow = _read(".github/workflows/backend-test.yml")
    assert "python-version-file: backend/.python-version" in workflow, "CI가 backend/.python-version을 읽지 않는다"
    assert not re.search(r"python-version:\s*[\"']?\d", workflow), "CI에 Python 버전을 직접 적지 않는다(backend/.python-version 하나만)"


def test_image_python_matches_the_version_file():
    found = re.search(r"^FROM python:(\d+\.\d+)", _read("backend/Dockerfile"), re.MULTILINE)
    assert found, "backend/Dockerfile에서 FROM python:<버전>을 못 찾았다"
    assert found.group(1) == _python_version(), (
        f"이미지 Python {found.group(1)}과 backend/.python-version {_python_version()}이 다르다 — 운영과 CI가 갈라진다"
    )


def test_postgis_images_are_the_same_everywhere():
    tags = {rel: POSTGIS_TAG.findall(_read(rel)) for rel in POSTGIS_FILES}
    missing = [rel for rel, found in tags.items() if not found]
    assert not missing, f"PostGIS 이미지 태그를 못 찾았다: {missing}"
    distinct = {tag for found in tags.values() for tag in found}
    assert len(distinct) == 1, f"PostGIS 이미지 버전이 파일마다 다르다: {tags}"


def test_postgis_images_match_the_production_database():
    """운영 DB는 RDS라 이미지 태그가 없다. deploy_rules.md 「배포 구성」의 DB 줄에 적은 버전과 맞춘다."""
    db_row = next(line for line in _read("deploy_rules.md").splitlines() if line.startswith("| DB |"))
    found = re.search(r"PostgreSQL (\d+)\.\d+, PostGIS (\d+\.\d+)", db_row)
    assert found, "deploy_rules.md 「배포 구성」 DB 줄에서 운영 PostgreSQL, PostGIS 버전을 못 찾았다"
    production = f"{found.group(1)}-{found.group(2)}"
    images = {tag for rel in POSTGIS_FILES for tag in POSTGIS_TAG.findall(_read(rel))}
    assert images == {production}, f"이미지 {images}가 운영 DB {production}과 다르다"
