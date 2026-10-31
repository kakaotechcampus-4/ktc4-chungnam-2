"""
사용자 기록을 다루는 목록 (#731, 멘토 리뷰 #680).

게스트 합치기(#560)는 PR 9개, 파일 31개, 모듈 7곳을 고쳤는데 agent는 빠졌다. 사용자 기록을 다루는 목록이 탈퇴(WITHDRAW_STEPS),
합치기(MERGE_STEPS), 지도 정리(maps.purge.PURGE_STEPS) 세 곳이라, 새 테이블이 생길 때 한쪽에만 더해졌다(코스 짜기도 탈퇴와
정리에만 들어감). #694는 처음 전환을 "같은 사용자에 로그인 수단 붙이기"로 바꿔 옮기기를 드물게 만들었지만, 이미 쓰던 카카오
계정으로 합칠 때는 여전히 이 목록을 탄다.

이 테스트는 목록이 테이블을 따라가는지 본다. 테이블은 모델 메타데이터(Base.metadata)에서 읽는다.
- 사용자 id를 담는 열(user_id, author_id, *_by)을 가진 테이블의 모듈은 MERGE_STEPS에 있다. 옮기지 않는 열은 NOT_MERGED에
  이유와 함께 적는다
- 그 모듈은 WITHDRAW_STEPS에도 있다. 탈퇴 때 그 모듈 기록을 그대로 두면 KEPT_ON_WITHDRAW에 이유와 함께 적는다
- WITHDRAW_STEPS의 모듈은 MERGE_STEPS에도 있다(auth/tests의 같은 검사를 여기서도 본다 — 목록 셋을 한 파일에서 읽게)
- 목록에 있는 모듈은 실제로 사용자 열을 가진 테이블을 소유한다(빈 단계가 남지 않게)

감지 기준은 열 이름이다. 모듈 경계 때문에 users를 FK로 가리키는 열은 user_identities.user_id 하나뿐이라 FK로는 못 찾는다.
이 테스트가 못 보는 것: JSONB 안의 사용자 id. pins.member_fulfillment와 candidates.member_fulfillment의 by_member[].user_id는
게시 시점의 충족 집계 사본이고 게스트 합치기에서 옮기지 않는다(2026-10-24 확인). 집계를 게시 뒤에 다시 계산하게 바뀌거나 by_member를
화면이 사람 식별에 쓰기 시작하면 다시 본다.
recommend_runs.applied_evidence(#847)의 작성자 id는 JSONB지만 탈퇴·나가기는 그 사람 줄을 빼고 합치기는 작성자를 옮긴다
(recommend/tests/test_first_run_847.py가 본다).
"""

import importlib
import re
from pathlib import Path

from common.database import Base

BACKEND = Path(__file__).resolve().parents[1]
USER_COLUMN = re.compile(r"^(user_id|author_id|recipient_user_id|[a-z_]+_by)$")

# auth는 합치기를 하는 쪽이다(users, user_identities는 auth가 직접 다룬다).
MERGER = "auth"

# (테이블, 열) -> 옮기지 않는 이유
NOT_MERGED: dict[tuple[str, str], str] = {
    ("maps", "created_by"): "게스트는 지도를 만들 수 없어(GUEST_NOT_ALLOWED) 게스트 id가 들어갈 일이 없다. 방장 판단은 memberships.role",
    ("event_log", "recipient_user_id"): "개인 채널 이벤트는 24시간 안의 것만 읽는다(realtime.service.RETENTION). 합친 뒤에는 새 세션이 새 이벤트를 받는다",
}

# 모듈 -> 탈퇴 때 그 모듈의 사용자 기록을 지우지 않는 이유. 다시 볼 조건: 탈퇴 정책(#10, #155)이 바뀔 때.
KEPT_ON_WITHDRAW: dict[str, str] = {
    "shortlist": "확정 리스트 항목은 지도의 결정이라 남기고, 담은 사람은 auth.api.display_names가 '탈퇴한 구성원'으로 보인다(#155)",
    "credits": "되살리면 잔액이 돌아와야 한다 — 7일 정리(auth.service.purge_withdrawn_user) 때 지운다(#948)",
    "common": "event_log는 24시간 안의 것만 읽고, 탈퇴한 사람의 세션은 이미 끊겨 받을 사람이 없다. 오래된 행을 지우는 작업은 아직 없다(deploy_rules.md)",
}


def _import_all_models() -> None:
    for path in sorted(BACKEND.glob("*/models.py")):
        importlib.import_module(f"{path.parent.name}.models")
    for path in sorted(BACKEND.glob("*/*/models.py")):   # agent/course 같은 하위 모듈
        rel = path.relative_to(BACKEND).with_suffix("")
        importlib.import_module(".".join(rel.parts))
    importlib.import_module("common.events")


def _owner_of_tables() -> dict[str, str]:
    _import_all_models()
    return {m.local_table.name: m.class_.__module__.split(".")[0] for m in Base.registry.mappers}


def _user_columns() -> dict[tuple[str, str], str]:
    owner = _owner_of_tables()
    return {
        (table.name, col.name): owner.get(table.name, "?")
        for table in Base.metadata.tables.values()
        for col in table.columns
        if USER_COLUMN.match(col.name)
    }


def _steps():
    from auth import service
    return [name for name, _ in service.MERGE_STEPS], [step[0] for step in service.WITHDRAW_STEPS]


def test_every_user_column_is_merged_or_explained():
    merge, _ = _steps()
    missing = sorted(
        f"{table}.{col} ({module})" for (table, col), module in _user_columns().items()
        if module != MERGER and module not in merge and (table, col) not in NOT_MERGED
    )
    assert not missing, (
        "사용자 id를 담는 열인데 그 모듈이 게스트 합치기(auth.service.MERGE_STEPS)에 없다. 그 모듈 api.py에 reassign_user를 열고 "
        f"MERGE_STEPS에 넣거나, 옮기지 않는 이유를 NOT_MERGED에 적는다: {missing}"
    )


def test_every_user_column_module_is_withdrawn_or_explained():
    _, withdraw = _steps()
    missing = sorted(
        {module for module in _user_columns().values()} - {MERGER} - set(withdraw) - set(KEPT_ON_WITHDRAW)
    )
    assert not missing, (
        "사용자 id 열을 가진 모듈인데 탈퇴(auth.service.WITHDRAW_STEPS)에 없다. 그 모듈 api.py에 탈퇴 처리를 열고 넣거나, "
        f"남기는 이유를 KEPT_ON_WITHDRAW에 적는다: {missing}"
    )


def test_kept_on_withdraw_modules_still_need_the_reason():
    _, withdraw = _steps()
    stale = sorted(set(KEPT_ON_WITHDRAW) & set(withdraw))
    gone = sorted(set(KEPT_ON_WITHDRAW) - set(_user_columns().values()))
    assert not stale, f"이제 탈퇴 목록에 있는 모듈이 KEPT_ON_WITHDRAW에 남아 있다 — 지운다: {stale}"
    assert not gone, f"사용자 열이 없어진 모듈이 KEPT_ON_WITHDRAW에 남아 있다 — 지운다: {gone}"


def test_not_merged_columns_still_exist():
    stale = sorted(set(NOT_MERGED) - set(_user_columns()))
    assert not stale, f"NOT_MERGED에 없는 열이 남아 있다 — 지운다: {stale}"


def test_withdraw_modules_are_also_merged():
    merge, withdraw = _steps()
    assert set(withdraw) <= set(merge), f"탈퇴에서 지우는데 합치기에서 옮기지 않는 모듈: {sorted(set(withdraw) - set(merge))}"


def test_listed_modules_own_user_columns():
    merge, withdraw = _steps()
    owners = set(_user_columns().values())
    empty = sorted((set(merge) | set(withdraw)) - owners)
    assert not empty, f"사용자 열이 없는데 목록에 있는 모듈 — 빈 단계다: {empty}"
