"""음식 종류 라벨 보정(#1093) — 업종 유래 거짓은 모름으로, 이름 규칙은 참으로. 순수 규칙과 적재 변환(DB 없이), 기존 DB 갱신 스크립트(DB)."""

import pytest
from sqlalchemy import func, select

from places import cuisine_names as cn
from places import ingest
from places.models import Place, PlaceFact
from places.scripts import relabel_cuisine_1093 as script

KEYS = ("cuisine_korean", "cuisine_chinese", "cuisine_japanese", "cuisine_western", "cuisine_bunsik", "cuisine_chicken_pub",
        "cuisine_bbq", "cuisine_foreign", "cuisine_raw_fish", "cuisine_buffet")


def _license(true_key):
    """업종이 true_key인 납품 라벨: 그 키만 참, 나머지는 전부 업종 유래 거짓(실제 납품 모양)."""
    return {k: {"value": "true" if k == true_key else "false", "evidence": "인허가 업태 'x'", "source": "license_business_type"} for k in KEYS}


def values(labels):
    return {k: v["value"] for k, v in labels.items()}


# ---- 순수 규칙 ----

def test_license_false_becomes_unknown_and_license_true_stays():
    out = cn.adjust_cuisine_labels("인사동두부마을", _license("cuisine_korean"))
    assert out["cuisine_korean"]["value"] == "true"
    assert all(out[k]["value"] == "unknown" and out[k]["evidence"] == "" and out[k]["source"] == "" for k in KEYS if k != "cuisine_korean")


def test_sushi_shop_with_a_korean_license_gets_japanese_and_raw_fish_true():
    out = cn.adjust_cuisine_labels("대규스시", _license("cuisine_korean"))
    assert (out["cuisine_japanese"]["value"], out["cuisine_raw_fish"]["value"]) == ("true", "true")
    assert out["cuisine_raw_fish"]["evidence"] == "가게 이름 '스시'" and out["cuisine_raw_fish"]["source"] == cn.NAME_SOURCE
    assert out["cuisine_korean"]["value"] == "unknown"   # 이름이 외국 음식이면 업종 유래 한식 참을 낮춘다(#1093, 루트 승인)


@pytest.mark.parametrize("name,key", [
    ("메이드인시카고피자", "cuisine_western"), ("bd버거", "cuisine_western"), ("마초스테이크", "cuisine_western"),
    ("팜티진쌀국수", "cuisine_foreign"), ("마포 원조 떡볶이", "cuisine_bunsik"), ("이공김밥", "cuisine_bunsik"),
    ("경성치킨", "cuisine_chicken_pub"), ("짬뽕의신화", "cuisine_chinese"), ("중화요리 팔공", "cuisine_chinese"),
    ("카라멘야", "cuisine_japanese"), ("갓덴스시", "cuisine_raw_fish"), ("막내회집", "cuisine_raw_fish"), ("연신내포항물회", "cuisine_raw_fish"),
])
def test_issue_examples_are_hit_by_the_name_rules(name, key):
    assert key in cn.name_hits(name)


@pytest.mark.parametrize("name", ["망우동 국밥", "화우동산", "도스타코스 시청배달점 국밥", "돼갈공명소바", "인사동두부마을", "스타벅스", "회기역 국밥집"])
def test_names_that_must_not_hit_the_sushi_udon_soba_rules(name):
    hits = cn.name_hits(name)
    assert "cuisine_raw_fish" not in hits and not ({"cuisine_japanese"} & hits.keys())   # 동 이름·말장난 상호·낱말 사이 이어붙임·회기(역 이름)


def test_foreign_name_lowers_a_license_korean_true_but_chicken_and_bunsik_do_not():
    assert cn.adjust_cuisine_labels("피자나라", _license("cuisine_korean"))["cuisine_korean"]["value"] == "unknown"
    for name in ("교촌치킨", "진미김밥", "원조 떡볶이"):
        assert cn.adjust_cuisine_labels(name, _license("cuisine_korean"))["cuisine_korean"]["value"] == "true"


def test_a_non_license_korean_true_is_left_alone():
    labels = _license("cuisine_korean")
    labels["cuisine_korean"] = {"value": "true", "evidence": "모범음식점", "source": "mobum"}
    assert cn.adjust_cuisine_labels("피자나라", labels)["cuisine_korean"]["value"] == "true"


def test_labels_other_than_license_false_and_other_keys_are_untouched():
    labels = {**_license("cuisine_korean"), "spicy_focused": {"value": "false", "evidence": "x", "source": "license_business_type"},
              "cuisine_bbq": {"value": "false", "evidence": "mobum 근거", "source": "mobum"}}
    out = cn.adjust_cuisine_labels("두부마을", labels)
    assert out["spicy_focused"] == labels["spicy_focused"] and out["cuisine_bbq"] == labels["cuisine_bbq"]   # cuisine_* 아님·업종 유래 아님
    assert labels["cuisine_chinese"]["value"] == "false"   # 입력은 바뀌지 않는다


def test_every_rule_word_and_key_is_real():
    assert set(cn.NAME_RULES) <= set(KEYS)
    assert all(words and all(w.strip() == w and w for w in words) for words in cn.NAME_RULES.values())


# ---- 적재 변환 ----

def _entry(place_id, name, labels):
    return {"place_id": place_id, "title": name, "labels": labels}


def test_curated_conversion_applies_to_restaurants_and_not_to_cafes():
    rows = list(ingest.curated_labels_to_rows([
        _entry("rest_R1", "갓덴스시", _license("cuisine_korean")),
        _entry("cafe_C1", "피자 카페", {"cuisine_korean": {"value": "false", "evidence": "x", "source": "license_business_type"}}),
    ]))
    rest = {r["fact_key"]: r for r in rows if r["source_id"] == "R1"}
    assert rest["cuisine_japanese"]["value"] == "true" and rest["cuisine_japanese"]["confidence"] == "known"
    assert rest["cuisine_chinese"]["confidence"] == "unknown" and rest["cuisine_chinese"]["value"] == ""
    cafe = next(r for r in rows if r["source_id"] == "C1")
    assert cafe["value"] == "false" and cafe["confidence"] == "known"   # 카페는 건드리지 않는다


def test_converted_rows_parse_into_unknown_labels_without_a_value():
    allowed = frozenset(KEYS)
    labels, report = ingest.parse_label_rows(ingest.curated_labels_to_rows([_entry("rest_R1", "두부마을", _license("cuisine_korean"))]), allowed)
    by_key = {l.fact_key: l for l in labels}
    assert by_key["cuisine_chinese"].confidence == "unknown" and by_key["cuisine_chinese"].value is None
    assert by_key["cuisine_korean"].value is True and report.accepted == len(KEYS)


# ---- 기존 DB 갱신 스크립트 ----

def _seed(db, sid, name, true_key="cuisine_korean", category="음식점"):
    place = Place(source="permit", source_id=sid, name=name, category=category, status="open",
                  geom=func.ST_SetSRID(func.ST_MakePoint(127.0, 37.5), 4326))
    db.add(place)
    db.flush()
    for key in KEYS:
        known_true = key == true_key
        db.add(PlaceFact(place_id=place.id, fact_key=key, value=known_true, confidence="known", source_layer=3,
                         evidence="인허가 업태 'x'", label_source="license_business_type"))
    db.flush()
    return place.id


def _fact(db, place_id, key):
    return db.execute(select(PlaceFact).where(PlaceFact.place_id == place_id, PlaceFact.fact_key == key)).scalar_one()


def test_dry_run_writes_nothing_and_reports_counts(db_session, capsys):
    pid = _seed(db_session, "1", "갓덴스시")
    rc = script.main([], session_factory=lambda: _NoClose(db_session))
    out = capsys.readouterr().out
    assert rc == 0 and "dry-run" in out and "바꿀 라벨 전체" in out and "갓덴스시" not in out
    assert _fact(db_session, pid, "cuisine_chinese").confidence == "known"   # 그대로


def test_apply_downgrades_false_raises_name_true_and_lowers_korean(db_session):
    sushi = _seed(db_session, "1", "갓덴스시")
    tofu = _seed(db_session, "2", "인사동두부마을")
    cafe = _seed(db_session, "3", "피자 카페", category="카페")
    assert script.main(["--apply"], session_factory=lambda: _NoClose(db_session)) == 0
    db_session.expire_all()
    f = _fact(db_session, sushi, "cuisine_raw_fish")
    assert (f.value, f.confidence, f.label_source, f.evidence) == (True, "known", "menu_keyword", "가게 이름 '스시'")
    assert _fact(db_session, sushi, "cuisine_korean").confidence == "unknown" and _fact(db_session, sushi, "cuisine_korean").value is None
    k = _fact(db_session, tofu, "cuisine_korean")
    assert (k.value, k.confidence) == (True, "known")   # 업종 유래 참은 그대로
    c = _fact(db_session, tofu, "cuisine_chinese")
    assert (c.value, c.confidence, c.evidence, c.label_source) == (None, "unknown", None, None)
    assert _fact(db_session, cafe, "cuisine_chinese").confidence == "known"   # 음식점만


def test_apply_is_idempotent_and_a_second_run_changes_nothing(db_session, capsys):
    _seed(db_session, "1", "갓덴스시")
    assert script.main(["--apply"], session_factory=lambda: _NoClose(db_session)) == 0
    capsys.readouterr()
    assert script.main([], session_factory=lambda: _NoClose(db_session)) == 0
    assert "바꿀 라벨 전체: 0" in capsys.readouterr().out
    assert db_session.scalar(select(func.count()).select_from(PlaceFact)) == len(KEYS)   # 새 행을 만들지 않는다


class _NoClose:
    """테스트 세션을 스크립트가 닫지 않게 감싼다(commit은 flush로 둔다 — 롤백되는 테스트 트랜잭션 안에서 본다)."""

    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        return getattr(self._db, name)

    def commit(self):
        self._db.flush()

    def close(self):
        pass
