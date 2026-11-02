"""음식 종류(`cuisine_*`) 라벨 보정(#1093) — 순수 함수, DB·파일을 모른다. 적재(`ingest.curated_labels_to_rows`)와 기존 DB 갱신 스크립트가 같이 쓴다.

납품 라벨은 음식 종류를 인허가 업종 한 칸으로 채운다: 업종이 「한식」이면 한식=참, 나머지는 전부 거짓(known). 업종은 실제로 파는 음식을 말해 주지
않아서(이름이 ○○스시인데 업종이 일식이면 회=거짓, 업종이 한식이면 일식=거짓) 업종으로 적은 「거짓」이 가게 이름과 어긋났다.
- **업종 유래 `cuisine_*` 거짓은 모름(unknown)으로 낮춘다.** 이 키들은 모두 soft·`unknown_policy=pass`라 모름은 실격시키지 않는다(가드레일 8).
  업종으로 채운 「참」은 그대로 둔다.
- **가게 이름 규칙이 걸리면 참으로 올린다**(스시·초밥 → 일식·회, 피자·버거 → 양식 …). 규칙 표는 아래 `NAME_RULES` 한 곳이다.
- 이름이 외국 음식 낱말(`FOREIGN_WORDS`)을 가리키는데 업종 유래 한식이 참이면(피자집이 업종 한식) 그 한식 참도 모름으로 낮춘다 — 「한식 말고」에서
  피자집이 실격되지 않게. 물회·횟집·회집·활어(회는 한국 음식)·분식·치킨은 한식을 낮추지 않는다.
`docs/constraints.md`의 `fact_key` 목록·`unknown_policy`는 바꾸지 않는다(값은 루트 소관).
"""

from __future__ import annotations

from typing import Mapping

LICENSE_SOURCE = "license_business_type"   # 업종으로 채운 라벨의 label_source
NAME_SOURCE = "menu_keyword"               # 가게 이름 규칙으로 올린 라벨의 label_source(납품본의 기존 이름 규칙과 같은 값)
KOREAN = "cuisine_korean"

# 우동·소바는 뺐다: 동 이름(망우동·화우동산)과 말장난 상호(돼갈공명소바)가 걸려 오탐이 났다(서울 음식점 8610곳 측정).
# 이름 규칙 표 — 키 → 가게 이름에 들어 있으면 그 음식 종류가 참인 낱말. 규칙을 바꾸면 여기만 고친다.
NAME_RULES: dict[str, tuple[str, ...]] = {
    "cuisine_japanese": ("스시", "초밥", "라멘", "돈까스", "돈카츠", "이자카야", "텐동", "규동"),
    "cuisine_raw_fish": ("스시", "초밥", "물회", "횟집", "회집", "활어", "사시미"),
    "cuisine_western": ("피자", "버거", "스테이크", "파스타"),
    "cuisine_chinese": ("짬뽕", "중화요리", "반점", "마라탕", "짜장"),
    "cuisine_bunsik": ("떡볶이", "김밥"),
    "cuisine_chicken_pub": ("치킨",),
    "cuisine_foreign": ("쌀국수", "팟타이", "타코", "케밥"),
}

# 이름이 외국 음식을 가리킨다고 볼 **낱말**(업종 유래 한식 참을 낮추는 근거). 키가 아니라 걸린 낱말로 본다 — 물회·횟집·회집·활어는 cuisine_raw_fish를
# 참으로 올리지만 한국 음식이라 한식을 낮추지 않는다. 분식·치킨도 한국 음식이라 뺀다. 한식 업종에서 흔한 짬뽕·짜장(한국식 중화)도 중식 낱말이라
# 낮춘다 — 업종 한식 중 이 낱말이 걸리는 수는 PR 본문에 적었다(서울 8610곳 측정).
FOREIGN_WORDS = frozenset({
    "스시", "초밥", "라멘", "돈까스", "돈카츠", "이자카야", "텐동", "규동", "사시미",   # 일식
    "피자", "버거", "스테이크", "파스타",                                          # 양식
    "짬뽕", "중화요리", "반점", "마라탕", "짜장",                                   # 중식
    "쌀국수", "팟타이", "타코", "케밥",                                            # 기타 외국
})


def name_hits(name: str) -> dict[str, str]:
    """가게 이름에 걸린 {fact_key: 걸린 낱말}. 이름 그대로 찾는다 — 공백을 지우면 낱말 사이가 이어져 엉뚱한 곳이 걸린다(도스타코스 시청 → 스시)."""
    text = (name or "").lower()
    hits: dict[str, str] = {}
    for key, words in NAME_RULES.items():
        word = next((w for w in words if w in text), None)
        if word is not None:
            hits[key] = word
    return hits


Label = dict   # {"value": "true|false|unknown", "evidence": str, "source": str} — 납품 JSON의 labels 항목 모양


def _is_license_false(key: str, label: Mapping) -> bool:
    return key.startswith("cuisine_") and str(label.get("source") or "") == LICENSE_SOURCE and str(label.get("value", "")).strip().lower() == "false"


def adjust_cuisine_labels(name: str, labels: Mapping[str, Mapping]) -> dict[str, Label]:
    """납품 라벨 {fact_key: {value, evidence, source}}의 cuisine_*를 보정한 새 dict(입력은 건드리지 않는다). cuisine_* 밖의 키는 그대로다.
    - 업종 유래 거짓 → 모름(value unknown, 근거 비움)
    - 이름 규칙에 걸린 키 → 참(근거 `가게 이름 '낱말'`, source menu_keyword)
    - 이름이 외국 음식이고 업종 유래 한식이 참 → 한식 모름(이름 규칙이 한식을 가리키지 않는 한)"""
    out: dict[str, Label] = {k: dict(v or {}) for k, v in labels.items()}
    hits = name_hits(name)
    for key, label in out.items():
        if _is_license_false(key, label):
            label.update(value="unknown", evidence="", source="")
    foreign = FOREIGN_WORDS & set(hits.values())
    for key, word in hits.items():
        out[key] = {"value": "true", "evidence": f"가게 이름 '{word}'", "source": NAME_SOURCE}
    korean = out.get(KOREAN)
    if foreign and korean is not None and KOREAN not in hits and str(korean.get("source") or "") == LICENSE_SOURCE \
            and str(korean.get("value", "")).strip().lower() == "true":
        korean.update(value="unknown", evidence="", source="")
    return out
