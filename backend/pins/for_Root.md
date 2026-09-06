# 루트 리뷰 가이드 — #16 backend/pins

전체 코드를 줄 단위로 다 읽을 필요는 없다. `docs/code-quality.md`의 리뷰 전략(위험도 높은 곳은
자세히, 반복적인 CRUD 보일러플레이트는 가볍게)을 그대로 적용한 순서다.

## 꼭 읽어야 할 것 (판단이 들어간 곳)

1. **이 PR 설명 자체** — 특히 "루트 확인 필요" 항목들. root가 실제로 결정해야 하는 부분이다.
2. **`pins/core.py`** — 순수 함수만 있어 짧다. 가드레일 1(비공개 후보 유출 금지) 판정이 전부 여기 모여 있다.
3. **`pins/service.py`의 `list_pins` WHERE 절과 `create_pin`의 IntegrityError 분기** — 외부 검수(Antigravity)에서 실제로 버그가 잡혔던 지점.
4. **`pins/deps.py`** — 다른 모듈(auth/maps/places/realtime) 자리를 채운 개발용 스텁. 뭐가 아직 가짜인지 알아야 나중에 교체 시점을 판단할 수 있다.

## 가볍게 훑거나 생략해도 되는 것

- `pins/models.py` — `docs/data-model.md` 그대로 옮긴 것
- `pins/schemas.py` — `docs/api-spec.yaml`과 1:1
- `pins/router.py` — 얇은 셸
- `backend/alembic/versions/0001_pins.py` — 마이그레이션
- `pins/tests/` — 42개 테스트 통과로 갈음
