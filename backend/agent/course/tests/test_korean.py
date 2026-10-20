"""조사 고르기 — 받침 경계, ㄹ 받침의 "로", 숫자·영문·괄호 끝, 모델이 쓴 조사 바로잡기, 화면 문장 템플릿."""

import pytest

from agent.course import core, goals as G, korean as kr
from agent.course.korean import attach
from agent.course.tests.fixtures import place, trip


@pytest.mark.parametrize("word,pair,expected", [
    ("책", "은/는", "책은"), ("나무", "은/는", "나무는"),
    ("책", "이/가", "책이"), ("나무", "이/가", "나무가"),
    ("책", "을/를", "책을"), ("나무", "을/를", "나무를"),
    ("책", "와/과", "책과"), ("나무", "와/과", "나무와"),
    ("책", "으로/로", "책으로"), ("나무", "으로/로", "나무로"),
    ("서울", "으로/로", "서울로"), ("플랫폼엘", "으로/로", "플랫폼엘로"),      # ㄹ 받침은 "로"
    ("플랫폼엘", "은/는", "플랫폼엘은"), ("서울", "을/를", "서울을"),
    ("강", "으로/로", "강으로"), ("한", "으로/로", "한으로"),
])
def test_한글_끝글자는_받침으로_고른다(word, pair, expected):
    assert attach(word, pair) == expected


@pytest.mark.parametrize("word,pair,expected", [
    ("관광4", "은/는", "관광4는"), ("관광1", "은/는", "관광1은"), ("관광0", "이/가", "관광0이"),   # 사 / 일 / 영
    ("관광2", "이/가", "관광2가"), ("관광3", "을/를", "관광3을"), ("관광5", "을/를", "관광5를"),   # 이 / 삼 / 오
    ("관광6", "와/과", "관광6과"), ("관광9", "와/과", "관광9와"),                              # 육 / 구
    ("관광1", "으로/로", "관광1로"), ("관광7", "으로/로", "관광7로"), ("관광8", "으로/로", "관광8로"),   # ㄹ 받침 숫자
    ("관광3", "으로/로", "관광3으로"), ("관광0", "으로/로", "관광0으로"), ("관광4", "으로/로", "관광4로"),
])
def test_숫자는_읽는_소리로_고른다(word, pair, expected):
    assert attach(word, pair) == expected


@pytest.mark.parametrize("word,pair,expected", [
    ("카페L", "은/는", "카페L은"), ("카페M", "으로/로", "카페M으로"), ("카페N", "이/가", "카페N이"),    # 엘 엠 엔
    ("카페R", "으로/로", "카페R로"), ("카페l", "은/는", "카페l은"),                                # 알(ㄹ)
    ("카페A", "은/는", "카페A는"), ("KT", "이/가", "KT가"), ("카페X", "을/를", "카페X를"),
])
def test_영문자는_알파벳_이름의_끝소리로_고른다(word, pair, expected):
    assert attach(word, pair) == expected


@pytest.mark.parametrize("word,pair,expected", [
    ("둘째 날 (화)", "으로/로", "둘째 날 (화)로"),          # 닫는 괄호는 건너뛰고 "화"를 본다
    ("스타벅스(강남점)", "은/는", "스타벅스(강남점)은"),
    ("카페 '봄'", "이/가", "카페 '봄'이"), ("책!", "은/는", "책!은"),
    ("카페(L)", "은/는", "카페(L)은"),
    ("()", "은/는", "()는"), ("", "을/를", "를"),             # 글자가 하나도 없으면 받침 없음
])
def test_괄호와_문장부호는_건너뛴다(word, pair, expected):
    assert attach(word, pair) == expected


def test_모르는_조사_쌍은_거절():
    with pytest.raises(ValueError):
        kr.josa("책", "은/가")


@pytest.mark.parametrize("rest,expected", [
    ("는 쉬어요", "은 쉬어요"), ("가 쉬어요", "이 쉬어요"), ("를 볼게요.", "을 볼게요."), ("과 함께", "과 함께"),
    ("로 가요", "으로 가요"), ("이곳은 좋아요", "이곳은 좋아요"),                # 조사처럼 보이지만 단어의 시작이면 건드리지 않는다
    ("가고 싶어요", "가고 싶어요"), ("에 가요", "에 가요"), ("", ""),
])
def test_모델이_쓴_조사를_받침에_맞춘다(rest, expected):
    assert kr.fix_particle_after("책", rest) == expected


def test_슬롯_뒤_조사는_실제_이름에_맞게_렌더된다():
    tr = trip(places=(place("p1", "관광지", 37.5, 127.0), place("p2", "관광지", 37.5, 127.0)))
    # 이름은 "장소P1이름"(름: ㅁ 받침) — 모델이 "는"이라고 써도 "은"이 된다. 날짜 라벨은 "...(월)"이라 받침 ㄹ — 괄호를 건너뛰고 "월"을 본다
    assert core.render_thought(tr, "{p1}는 {d1}에 쉬어요") == "장소P1이름은 첫째 날 (월)에 쉬어요"
    assert core.render_thought(tr, "{d1}은 {p2}가 좋아요") == "첫째 날 (월)은 장소P2이름이 좋아요"
    assert core.render_thought(tr, "{p1}와 {p2}를 같이 봐요") == "장소P1이름과 장소P2이름을 같이 봐요"
    assert core.render_thought(tr, "{p1}이곳은") == "장소P1이름이곳은"


def test_템플릿에는_병기_조사가_남지_않는다():
    import re
    import pathlib
    root = pathlib.Path(core.__file__).parent
    leftover = []
    for f in [*root.glob("*.py"), *(root / "eval").glob("*.py")]:
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"[가-힣](은\(는\)|는\(은\)|이\(가\)|가\(이\)|을\(를\)|를\(을\)|와\(과\)|과\(와\)|으로\(로\)|\(으\)로)", line) and "korean.py" not in str(f) and "#" not in line.split('"')[0]:
                leftover.append(f"{f.name}:{n}")
    assert leftover == []


def test_목표_문구와_질문은_받침에_맞는_조사를_쓴다():
    tr = trip(places=(place("p1", "관광지", 37.5, 127.0), place("p2", "카페", 37.5, 127.0)))
    assert G.label(tr, G.Goal("place_on_day", "d1", ("p1",))) == "장소P1이름을 첫째 날 (월)에"
    assert G.label(tr, G.Goal("together", None, ("p1", "p2"))) == "장소P1이름 · 장소P2이름 같은 날"
