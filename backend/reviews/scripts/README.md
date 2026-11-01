# 후기 관리 스크립트

관리자 화면 대신 쓴다(docs/credits-reviews.md 5절 「숨김」, 10절, #432 D8). `backend/`에서 실행한다. DB 주소는 `DATABASE_URL`(.env)을 따른다.
신고는 매일 확인한다(명세 10절 — 권리침해 게시물 임시조치는 요청을 받으면 지체 없이). 신고 수로 자동 숨기는 기준은 아직 없다.

## 신고 목록

```
python -m reviews.scripts.reports            # 숨기지 않은 후기, 신고 많은 순 20개
python -m reviews.scripts.reports --limit 50
python -m reviews.scripts.reports --all      # 숨긴 후기도 [숨김] 표시와 함께
```

후기마다 review_id, 신고 수, 마지막 신고 시각, 장소 이름과 place_id, 별점, 글을 출력한다. 작성자와 신고자는 출력하지 않는다.
읽기 전용이다. 출력은 터미널에서만 보고 파일·채널에 옮기지 않는다(모르는 사람이 쓴 글이다).

## 숨기기·되돌리기

```
python -m reviews.scripts.hide <review_id>          # 숨기기
python -m reviews.scripts.hide <review_id> --undo   # 되돌리기
```

숨긴 후기는 목록·평균·개수·mine에서 빠지고 신고할 수 없다. 작성자 본인에게도 안 보인다. 신고 행은 남는다.
작성자가 숨긴 후기를 고쳐도 숨김은 그대로다. 작성자는 숨긴 후기를 지울 수 없다(404) — 지우고 다시 써서 숨김을 푸는 길이 없다.

## 집계 확인 (SQL)

하루 신고 수와 숨김 수(Asia/Seoul, 최근 14일):

```sql
SELECT (created_at AT TIME ZONE 'Asia/Seoul')::date AS day, count(*) AS reports
FROM review_reports
WHERE created_at >= now() - interval '14 days'
GROUP BY 1 ORDER BY 1;

SELECT (hidden_at AT TIME ZONE 'Asia/Seoul')::date AS day, count(*) AS hidden
FROM reviews
WHERE hidden_at >= now() - interval '14 days'
GROUP BY 1 ORDER BY 1;
```

첫 신고에서 숨김까지 걸린 시간:

```sql
SELECT r.id, r.hidden_at - min(rr.created_at) AS took
FROM reviews r JOIN review_reports rr ON rr.review_id = r.id
WHERE r.hidden_at IS NOT NULL
GROUP BY r.id ORDER BY took DESC;
```
