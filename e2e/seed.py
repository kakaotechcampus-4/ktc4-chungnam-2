"""E2E 시드(#1281): 성수 가상 정예 음식점 6곳(라벨 포함)과 사용자 둘(방장, 구성원)의 세션 쿠키. 쿠키는 JSON으로 출력한다.

backend 폴더에서 백엔드와 같은 DATABASE_URL, SESSION_SECRET으로 돈다: `cd backend && python ../e2e/seed.py`.
- 장소는 backend/integration/real_places_fixtures.py와 같은 방식이다(places.repository로 적재하고 정예로 켠다). 다시 돌려도 같은 행이다.
- 쿠키는 auth.testing.session_cookie가 만든다 — 실제 인증과 같은 서명 토큰과 users 행이다(#126). 카카오 로그인을 대신한다.
  사용자는 실행마다 새로 만든다(테스트끼리 지도가 섞이지 않게).
"""

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from sqlalchemy import update  # noqa: E402

from auth.testing import create_kakao_user, session_cookie  # noqa: E402
from common.database import SessionLocal, session_scope  # noqa: E402
from places import repository  # noqa: E402
from places.ingest import LabelRow, PlaceRow  # noqa: E402
from places.models import Place  # noqa: E402

LABELED_AT = datetime(2026, 10, 2, tzinfo=timezone.utc)

# (source_id, 이름, 위도, 경도, {fact_key: value}) — 전부 성수 중심 700m 안
PLACES = {
    "e2e-K": ("성수 한식집", 37.5447, 127.0563, {"cuisine_korean": True, "cuisine_raw_fish": False, "spicy_focused": False}),
    "e2e-R": ("성수 횟집", 37.5449, 127.0558, {"cuisine_korean": False, "cuisine_raw_fish": True, "spicy_focused": False}),
    "e2e-B": ("성수 분식집", 37.5441, 127.0566, {"cuisine_korean": False, "cuisine_raw_fish": False, "spicy_focused": False}),
    "e2e-S": ("성수 매운집", 37.5443, 127.0554, {"cuisine_korean": False, "cuisine_raw_fish": False, "spicy_focused": True}),
    "e2e-C": ("성수 조개구이", 37.5451, 127.0569, {"cuisine_korean": False, "cuisine_raw_fish": False, "spicy_focused": False}),
    "e2e-U": ("성수 이름모를집", 37.5439, 127.0560, {}),
}


def seed_places(db) -> None:
    repository.upsert_places(db, [
        PlaceRow("permit", sid, name, "음식점", f"서울 성동구 성수동 {sid}", None, lat, lng, "open")
        for sid, (name, lat, lng, _) in PLACES.items()
    ])
    repository.upsert_facts(db, [
        LabelRow("permit", sid, key, value, "known", 3, LABELED_AT)
        for sid, (_, _, _, facts) in PLACES.items() for key, value in facts.items()
    ])
    db.execute(update(Place).where(Place.source == "permit", Place.source_id.in_(list(PLACES))).values(curated=True))


def main() -> None:
    out = {}
    with session_scope(SessionLocal()) as db:
        seed_places(db)
        for role, name in (("owner", "방장"), ("member", "구성원")):
            user = create_kakao_user(db, str(uuid.uuid4()), display_name=name)
            out[role] = {"user_id": user.id, "name": name, **session_cookie(user.id)}
    print(json.dumps(out))


if __name__ == "__main__":
    main()
