"""#1253: pingo_eval에서 라벨만 읽어 필터와 순위를 계산한다. 어떤 행도 쓰지 않는다."""
import os
from urllib.parse import urlparse

import psycopg2

from recommend import core


def _sample(cursor, category, key, value):
    cursor.execute("""
        SELECT p.id::text, f.value, f.confidence::text
        FROM places p JOIN place_facts f ON f.place_id = p.id
        WHERE p.category = %s AND p.curated AND p.status = 'open' AND f.fact_key = %s
          AND ((%s = 'unknown' AND (f.value IS NULL OR f.confidence = 'unknown'))
            OR (%s <> 'unknown' AND f.confidence = 'known' AND f.value = to_jsonb(CAST(%s AS boolean))))
        ORDER BY p.id LIMIT 1
    """, (category, key, value, value, None if value == "unknown" else value))
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError(f"평가 라벨 없음: {category} {key} {value}")
    known = row[1] is not None and row[2] == "known"
    return row[0], core.build_check(key, "pass", known=known, value=row[1], passes=bool(row[1]))


def run_readonly():
    url = os.environ.get("DATABASE_URL", "postgresql://pingo:pingo@localhost:5432/pingo_eval")
    parsed = urlparse(url)
    if parsed.hostname not in ("localhost", "127.0.0.1", "::1") or parsed.path != "/pingo_eval":
        raise RuntimeError("로컬 pingo_eval만 허용한다")
    with psycopg2.connect(url) as conn:
        conn.set_session(readonly=True, autocommit=False)
        with conn.cursor() as cur:
            spicy = [_sample(cur, "음식점", "spicy_focused", state) for state in ("true", "false", "unknown")]
            accessible = [_sample(cur, "관광지", "accessible", state) for state in ("false", "true", "unknown")]
        spicy_checks = dict(spicy)
        baseline = list(spicy_checks)
        for authors in (frozenset({"a"}), frozenset({"a", "b"})):
            scores = core.score_candidates({pid: [check] for pid, check in spicy}, [], {}, {}, {"spicy_focused": authors})
            flags = core.apply_disqualifier_filters([[check] for _, check in spicy])
            ranking = sorted(baseline, key=lambda pid: -scores[pid])
            assert all(flags) and scores[baseline[0]] == -3 * len(authors) and scores[baseline[2]] == 0
            assert ranking[-1] == baseline[0] and len(ranking) == len(baseline)
            print(f"매운맛 {len(authors)}명: 후보 {len(baseline)} 유지, 점수 {scores[baseline[0]]}, 순위 변경")
        flags = core.apply_disqualifier_filters([[check] for _, check in accessible], [("accessible", True)])
        assert flags == [False, True, True] and accessible[2][1].needs_check
        print("접근성: known 거짓만 제외, 참·모름 통과, 모름 확인 필요")
