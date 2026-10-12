"""
docs/permissions.md(정본)의 YAML 블록을 그대로 옮긴 선언. 이 파일은 정본을 "전사"할 뿐,
값을 바꾸는 곳이 아니다 — 역할·범위·액션 목록이 바뀌면 루트가 먼저 docs/permissions.md를
고치고, 이 파일은 그걸 따라간다(authz/CLAUDE.md "넘지 말 것").

authz/tests/test_policy_drift.py가 이 선언과 docs/permissions.md·docs/api-spec.yaml을
실제로 파싱해 대조한다 — 정본이 바뀌었는데 여기를 안 고치면 그 테스트가 잡는다.
"""

from dataclasses import dataclass
from typing import Literal, Mapping

Role = Literal["member", "owner"]  # memberships.role — DB에는 이 둘만 있다. author는 저장되지 않고
# evidence_lines.author_id / recommend_runs.requested_by로부터 리소스별로 파생된다.

ResourceType = Literal["map", "pin", "evidence_line", "candidate", "run", "shortlist_item"]


@dataclass(frozen=True)
class RoleSpec:
    scope: Mapping[str, str]
    actions: frozenset[str]


POLICY: Mapping[str, RoleSpec] = {
    "member": RoleSpec(
        scope={"map": "own"},
        actions=frozenset(
            {
                "pin.create",
                "pin.delete",  # "구성원 누구나" (9/4 결정 #25)
                "pin.react",
                "pin.revert",
                "shortlist.add",
                "shortlist.remove",  # "구성원 누구나" (5-3, 15-1)
                "evidence.add",
                "recommend.request",
                "recommend.evidence",  # 근거 조회·토글·추가 — 지도 구성원 누구나(#32 결정,
                                        # 2026-09-23: "근거 목록은 구성원별로 한 줄씩 따로 뜬다",
                                        # 최종기획안 5-5). run.requested_by 본인 제한 없음.
                                        # 개별 근거 줄 비활성화(evidence.disable)는 그 줄
                                        # 작성자 본인만(author).
                "invite.create",  # 초대 링크 발급 — "구성원 누구나" (#4 결정, maps/for_Root.md 항목 4)
                "map.leave",  # 지도 나가기(#369). 넘길 사람이 없는 방장 차단은 역할이 아니라 지도 상태라
                               # 여기 넣지 않고 maps/core.py가 판정한다(409 OWNER_CANNOT_LEAVE)
                "route.recalculate",  # 동선 재계산 — "구성원 누구나" (#103 결정, shortlist/for_Root.md 1번)
            }
        ),
    ),
    "author": RoleSpec(
        scope={"evidence_line": "own", "candidate": "own", "run": "own"},
        actions=frozenset(
            {
                "evidence.disable",  # '-'로 빼기 — "자기가 쓴 것만" (5-5)
                "recommend.manage",  # run 하위 실행계(지역확인·실행·결과조회·반경넓히기·재시도) —
                                      # run.requested_by 본인만(가드레일1)
                "recommend.publish",  # 「지도에 올리기」 — candidate.requested_by 본인만
            }
        ),
    ),
    "owner": RoleSpec(
        scope={"map": "own"},
        actions=frozenset(
            {
                "member.kick",  # v2, #8
                "map.settings.edit",
                "map.delete",  # 지도 삭제(#369). 방장만, soft delete
            }
        ),
    ),
}

# permissions.md에는 액션이 어떤 리소스 종류에 쓰이는지가 없다 — 없으면
# can(user, "recommend.publish", Resource(type="pin", ...))처럼 액션과 무관한 리소스 종류에 대해
# 판정을 묻는 타입 혼동이 조용히 통과한다. 이 표는 정본을 "좁히기만" 한다(정본에 없는 액션을
# 허용하지 않고, 정본에 있는 액션의 유효 대상만 못 박는다) — for_Root.md에 정본 승격 여부 확인 요청.
ACTION_RESOURCE_TYPES: Mapping[str, frozenset[ResourceType]] = {
    "pin.create": frozenset({"map"}),
    "pin.delete": frozenset({"pin"}),
    "pin.react": frozenset({"pin"}),
    "pin.revert": frozenset({"pin"}),
    # add의 대상은 pin이다 — POST /maps/{mapId}/shortlist의 본문이 {pin_id}.
    "shortlist.add": frozenset({"pin"}),
    # remove만 두 종류를 받는다. 실행 경로는 DELETE /shortlist/{itemId}(shortlist_item)이지만,
    # api-spec의 Pin 스키마에도 can_remove_from_shortlist가 붙어 있어(확정 핀을 리스트에서 뺄 수
    # 있는지를 핀 응답 자체가 표시한다) 표시용 판정은 pin으로도 물어보게 된다. 둘 다 정당하다.
    "shortlist.remove": frozenset({"pin", "shortlist_item"}),
    "evidence.add": frozenset({"map"}),
    "evidence.disable": frozenset({"evidence_line"}),
    "recommend.request": frozenset({"map"}),
    "recommend.evidence": frozenset({"run"}),  # recommend/loaders.py::load_run이 Resource(type="run", ...)로 채운다
    "recommend.manage": frozenset({"run"}),  # recommend/loaders.py::load_run이 Resource(type="run", ...)로 채운다
    "recommend.publish": frozenset({"candidate"}),
    "member.kick": frozenset({"map"}),
    "map.settings.edit": frozenset({"map"}),
    "map.delete": frozenset({"map"}),
    "map.leave": frozenset({"map"}),
    "invite.create": frozenset({"map"}),
    "route.recalculate": frozenset({"map"}),
}
