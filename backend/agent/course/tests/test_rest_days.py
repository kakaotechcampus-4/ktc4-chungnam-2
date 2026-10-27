"""휴무 글 읽기 — 관광지 rest_days에 실제로 나오는 문장들로 경계를 시험한다."""

import pytest

from agent.course.rest_days import known_weekdays, merge_sources, parse_rest_days, read_hours


def row(text: str) -> str:
    """월~일을 o(영업)/c(휴무)/u(모름) 일곱 글자로."""
    h = parse_rest_days(text)
    assert set(h) == set(range(7))
    return "".join(h[i][0] for i in range(7))


@pytest.mark.parametrize("text, expected", [
    ("연중무휴", "ooooooo"),
    ("연중 무휴", "ooooooo"),
    ("휴무없음", "ooooooo"),
    ("연중무휴※ 전시관 휴관일은 공식 홈페이지 참조", "ooooooo"),
    ("연중무휴(단, 설날/추석 당일 휴무)", "ooooooo"),
    ("매주 월요일", "coooooo"),
    ("매주일요일", "ooooooc"),
    ("월요일 휴무", "coooooo"),
    ("매주 월요일 / 1월 1일 / 설·추석 연휴", "coooooo"),
    ("매주 월요일 (단, 월요일이 공휴일인 경우 정상 개관) / 1월 1일", "coooooo"),
    ("매주 월요일<br>※ 단, 정기휴일이 공휴일 및 대체공휴일과 겹칠 경우에는 개방하며", "coooooo"),
    ("매주 월요일, 설날/추석 당일", "coooooo"),
    ("공휴일을 제외한 매주 월요일, 1월 1일", "coooooo"),
    ("매주 월요일~화요일", "ccooooo"),
    ("매주 월요일,화요일 정기휴무", "ccooooo"),
    ("매주 일요일~월요일", "coooooc"),          # 일요일에서 월요일로 넘어가는 범위
    ("매주 일요일~목요일", "ccccooc"),
    ("매주 토요일, 일요일 / 법정공휴일", "ooooocc"),
    ("토요일+일요일", "ooooocc"),
    ("주말 및 공휴일", "ooooocc"),
    ("1월 1일 / 설·추석", "ooooooo"),            # 공휴일만 — 요일 휴무 없음
    ("법정공휴일", "ooooooo"),
    ("일요일을 제외한 법정공휴일", "ooooooo"),    # 일요일은 휴무가 아니라 예외다
    ("매주 월요일 / 5월 1일 / 1월 1일", "coooooo"),
])
def test_읽히는_글(text, expected):
    assert row(text) == expected
    assert known_weekdays(parse_rest_days(text))


@pytest.mark.parametrize("text", [
    "", "   ", "공연 별로 상이함", "점포별 상이", "※ 자세한 사항은 전화문의 요망", "홈페이지 참조",
    "[사무실]매주 월요일", "[휴관일]1월 1일 / 설·추석 당일[정기휴실일]매년 3월, 6월, 9월, 12월 첫 번째 월요일",
    "[워터파크] 매주 화요일~수요일<br> [찜질스파] 연중무휴", "월 1회 휴관 함으로 홈페이지 참조",
    "전시기간 외 휴관※ 전시기간에는 연중무휴", "평일 (학생 안전강화로 인해 주말에만 개방)",
])
def test_모르는_글은_전부_unknown(text):
    assert row(text) == "uuuuuuu"
    assert not known_weekdays(parse_rest_days(text))


def test_None도_모름():
    assert parse_rest_days(None) == {wd: "unknown" for wd in range(7)}


@pytest.mark.parametrize("text, expected", [
    ("매월 첫째, 셋째 수요일", "oouoooo"),
    ("매월 마지막 월요일 / 1월 1일", "uoooooo"),
    ("매주 월요일 / 매월 두번째·네번째 화요일", "cuuuuuu"),          # 월요일은 확실, 이해 못 한 조각이 있어 나머지는 모름
    ("연중무휴 (매주 월요일은 포장 영업만 가능)", "uoooooo"),
    ("- 묘지 : 연중무휴 <br> - 기념관 : 매주 월요일", "uoooooo"),     # 시설별로 다른 글 — 어느 쪽인지 모름
    ("1, 2, 7, 8월 토요일 / 매주 일요일", "ooooouc"),                # 달이 정해진 토요일은 모름
    ("매주 월요일 / 우천, 태풍, 혹한 등 기상 악화 시", "cuuuuuu"),
])
def test_일부만_읽히면_읽힌_요일만_확정(text, expected):
    assert row(text) == expected
    assert not known_weekdays(parse_rest_days(text))


def test_합치기는_모름을_채우고_충돌은_모름으로():
    merged = merge_sources(parse_rest_days("매월 첫째 월요일"), parse_rest_days("매주 월요일"))
    assert merged[0] == "closed" and merged[1] == "open"
    conflict = merge_sources(parse_rest_days("연중무휴"), parse_rest_days("매주 월요일"))
    assert conflict[0] == "unknown" and conflict[1] == "open"
    assert merge_sources(parse_rest_days(""), parse_rest_days("")) == {wd: "unknown" for wd in range(7)}


def test_구조화_칸_없으면_모름_빈목록이면_매일_영업():
    assert read_hours(None, None) == {wd: "unknown" for wd in range(7)}
    assert read_hours([], None) == {wd: "open" for wd in range(7)}
    assert read_hours(["월", "일"], None) == {0: "closed", **{wd: "open" for wd in range(1, 6)}, 6: "closed"}


def test_hours는_요일별_영업_여부만_본다():
    full = {d: [["09:00", "18:00"]] for d in "월화수목금토일"}
    assert read_hours([], full) == {wd: "open" for wd in range(7)}
    # closed_days 칸이 없으면 hours만으로 판정: 빈 요일은 휴무, 시간이 있으면 영업, 요일 칸이 없으면 모름
    got = read_hours(None, {**full, "월": []})
    assert got[0] == "closed" and got[1] == "open"
    got = read_hours(None, {"화": [["12:30", "20:00"]]})
    assert got[1] == "open" and got[0] == "unknown" and got[6] == "unknown"
    # closed_days만 있고 hours 칸이 없으면 closed_days를 따른다
    assert read_hours(["월"], {})[0] == "closed"


def test_두_칸이_어긋나는_요일은_hours를_따른다():
    full = {d: [["09:00", "18:00"]] for d in "월화수목금토일"}
    # 휴무라는데 시간이 있음 / 영업이라는데 시간 목록이 빔 — 둘 다 hours가 이긴다(places.core.day_open_status, #747)
    got = read_hours(["화"], {**full, "일": []})
    assert got[1] == "open" and got[6] == "closed" and got[0] == "open"
    assert read_hours(["월"], {**full, "월": []})[0] == "closed"


def test_자정을_넘기는_시각도_영업으로_읽는다():
    got = read_hours([], {"금": [["18:00", "26:00"]], "토": [["00:00", "24:00"]]})
    assert got[4] == "open" and got[5] == "open" and got[6] == "open"


def test_hours로_모자란_요일은_글로_채우되_어긋나면_모름():
    # closed_days 없음 + hours는 월만 앎 → 나머지는 글로
    got = read_hours(None, {"월": [["09:00", "18:00"]]}, "매주 화요일")
    assert got[0] == "open" and got[1] == "closed"
    # hours(월 영업)와 글(월 휴무)이 어긋나면 모름
    assert read_hours(None, {"월": [["09:00", "18:00"]]}, "매주 월요일")[0] == "unknown"
    # closed_days가 있으면 글은 쓰지 않는다
    assert read_hours(["월"], None, "연중무휴")[0] == "closed"


def test_글_읽기는_closed_days_칸이_없을_때만():
    assert read_hours([], None, "매주 월요일")[0] == "open"
    assert read_hours(None, None, "매주 월요일")[0] == "closed"
    assert read_hours(None, None, None) == {wd: "unknown" for wd in range(7)}
