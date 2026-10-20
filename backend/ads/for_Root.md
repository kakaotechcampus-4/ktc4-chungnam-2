# ads → 루트 보고

## 1. places.api에 자체 DB 이름 검색 함수가 없다 (find_place 보류, #648)

`docs/ads.md` 8절의 `python -m ads.scripts.find_place "<이름 일부>" --category 카페`는 places에서 이름으로 후보를 찾아
place_id, 이름, 주소, status를 출력해야 한다. places.api에 있는 이름 검색 `search_by_name`은 카카오(dev는 고정 샘플)를 부르고
자체 DB를 보지 않으며 status도 주지 않는다. 그래서 스크립트를 만들지 않았다.

필요한 시그니처(제안):

```python
def search_own_by_name(db: Session, *, query: str, category: str | None = None, limit: int = 20) -> list[dict]:
    """자체 DB places에서 이름 부분 일치(대소문자 무시). status와 무관하게 돌려준다(closed도 보여야 고르지 않는다).
    [{id, name, address, category, status}] 이름순. 읽기 전용, 커밋하지 않는다."""
```

함수가 열리면 ads가 `scripts/find_place.py`를 붙인다. 그동안은 `scripts/README.md`의 읽기 전용 SQL로 찾는다.

## 2. 등록 스크립트의 status=open 확인

places.api에 status를 주는 함수가 없어 `get_places`로 좌표를 읽은 뒤, 그 좌표를 중심으로 `get_ad_places`(반경 1m,
추천 대상 카테고리)를 불러 결과에 있으면 open으로 본다. 위 1번 함수가 status를 주면 그쪽으로 바꿀 수 있다.
