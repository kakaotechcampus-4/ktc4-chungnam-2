"""한국어 조사 고르기 — 화면 문장 템플릿에서 "은(는)"처럼 병기하지 않고 받침을 보고 하나만 붙인다. 순수 함수다.

끝 글자가 한글이면 받침으로, 아니면 읽는 소리 기준의 단순한 규칙으로 정한다:
- 숫자는 읽는 소리의 끝(영·일·삼·육·칠·팔은 받침 있음, 이·사·오·구는 없음; "공"이 아니라 "영")
- 영문자는 알파벳 이름의 끝소리(L 엘, M 엠, N 엔, R 알만 받침 있음)
- 닫는 괄호·공백·문장부호는 건너뛰고 그 앞 글자를 본다. 건너뛰고 나서도 글자가 없으면 받침 없음으로 본다.
"으로/로"는 받침이 없거나 ㄹ 받침이면 "로"다.
"""

from __future__ import annotations

import re

# 쌍 이름 → (받침 있을 때, 없을 때). "와/과"는 이름과 달리 받침이 있으면 "과"다.
_PAIR_FORMS = {"은/는": ("은", "는"), "이/가": ("이", "가"), "을/를": ("을", "를"), "와/과": ("과", "와"), "으로/로": ("으로", "로")}
PAIRS = tuple(_PAIR_FORMS)
_SKIP = " \t\n)]}>」』’”'\".,!?·…~-:;"
_DIGIT_FINAL = {"0": True, "1": True, "2": False, "3": True, "4": False, "5": False, "6": True, "7": True, "8": True, "9": False}
_LETTER_FINAL = {"l": True, "m": True, "n": True, "r": True}      # 엘, 엠, 엔, 알
_RIEUL_DIGITS = {"1", "7", "8"}                                     # 일, 칠, 팔
_RIEUL_LETTERS = {"l", "r"}


def _final(word: str) -> tuple[bool, bool]:
    """(받침이 있는가, 그 받침이 ㄹ인가)."""
    for ch in reversed(word):
        if ch in _SKIP:
            continue
        if "가" <= ch <= "힣":
            jong = (ord(ch) - 0xAC00) % 28
            return jong != 0, jong == 8
        if ch in _DIGIT_FINAL:
            return _DIGIT_FINAL[ch], ch in _RIEUL_DIGITS
        low = ch.lower()
        if "a" <= low <= "z":
            return _LETTER_FINAL.get(low, False), low in _RIEUL_LETTERS
    return False, False


def josa(word: str, pair: str) -> str:
    """조사만 돌려준다. pair는 PAIRS 중 하나."""
    if pair not in PAIRS:
        raise ValueError(f"모르는 조사 쌍 {pair}")
    has, rieul = _final(word)
    with_final, without = _PAIR_FORMS[pair]
    if pair == "으로/로":
        return without if (not has or rieul) else with_final
    return with_final if has else without


def attach(word: str, pair: str) -> str:
    return word + josa(word, pair)


_PARTICLE = re.compile(r"(으로|은|는|이|가|을|를|와|과|로)(?=[\s.,!?)]|$)")
_PAIR_OF = {"은": "은/는", "는": "은/는", "이": "이/가", "가": "이/가", "을": "을/를", "를": "을/를", "와": "와/과", "과": "와/과",
            "으로": "으로/로", "로": "으로/로"}


def fix_particle_after(word: str, rest: str) -> str:
    """word 바로 뒤에 오는 글(rest)이 조사로 시작하면 word의 받침에 맞게 바로잡는다. 모델이 "{p4}는"처럼 쓴 것을 실제 이름에 맞춘다.
    조사 뒤가 공백·문장부호·끝일 때만 조사로 본다("{p4}이곳" 같은 단어를 건드리지 않는다)."""
    m = _PARTICLE.match(rest)
    if not m:
        return rest
    return josa(word, _PAIR_OF[m.group(1)]) + rest[m.end(1):]
