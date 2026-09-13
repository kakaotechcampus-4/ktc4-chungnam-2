"""포트별 계약 테스트의 공통 뼈대 — dev 구현과 real 구현에 똑같은 단언을 돌린다."""

import inspect


def assert_signature_matches(protocol: type, impl: type) -> None:
    """Protocol의 메서드 이름·인자 이름·인자 타입·반환 타입이 구현과 같은지 본다.

    real 구현이 없는 지금도 돌아가고(스텁만 검사), real이 들어오면 그날부터 드리프트를 잡는다.

    한계(DeepSeek 검수 지적, 알고 감수함): 타입 비교는 `str(annotation)` 문자열 비교라
    `str | None`과 `Optional[str]`처럼 의미는 같지만 표기가 다르면 오탐이 난다. 대신 양쪽 다
    타입 힌트가 **없는** 경우는 명시적으로 실패시킨다(그렇지 않으면 아무 것도 안 적은 두
    구현이 트리비얼하게 통과해버려 계약 검사가 무의미해진다). 프로젝트 컨벤션(모든 Protocol·
    구현이 완전한 타입 힌트를 쓴다)을 지키는 한 문자열 비교로 충분하다."""
    problems: list[str] = []
    for name, member in vars(protocol).items():
        if name.startswith("_") or not callable(member):
            continue
        actual = getattr(impl, name, None)
        if actual is None:
            problems.append(f"{impl.__name__}에 {name}()가 없다")
            continue
        want = [p for n, p in inspect.signature(member).parameters.items() if n != "self"]
        got = [p for n, p in inspect.signature(actual).parameters.items() if n != "self"]
        if [p.name for p in want] != [p.name for p in got]:
            problems.append(f"{name}: 인자 이름 {[p.name for p in want]} != {[p.name for p in got]}")
            continue
        for p_want, p_got in zip(want, got):
            if p_want.annotation is inspect.Parameter.empty or p_got.annotation is inspect.Parameter.empty:
                problems.append(f"{name}.{p_want.name}: 타입 힌트가 없다 — 계약 검사가 불가능하다")
            elif str(p_want.annotation) != str(p_got.annotation):
                problems.append(f"{name}.{p_want.name}: 인자 타입이 다르다 "
                                f"({p_want.annotation} != {p_got.annotation})")
        want_ret = inspect.signature(member).return_annotation
        got_ret = inspect.signature(actual).return_annotation
        if want_ret is inspect.Signature.empty or got_ret is inspect.Signature.empty:
            problems.append(f"{name}: 반환 타입 힌트가 없다 — 계약 검사가 불가능하다")
        elif str(want_ret) != str(got_ret):
            problems.append(f"{name}: 반환 타입이 다르다 ({want_ret} != {got_ret})")
    assert not problems, f"{protocol.__name__} 계약 위반: " + "; ".join(problems)
