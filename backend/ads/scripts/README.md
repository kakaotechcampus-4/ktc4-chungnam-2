# 광고 관리 스크립트

관리자 화면 대신 쓴다(docs/ads.md 8절). `backend/`에서 실행한다. DB 주소는 `DATABASE_URL`(.env)을 따른다.

## 등록

```
python -m ads.scripts.register --csv ads.csv --dry-run   # 검증만
python -m ads.scripts.register --csv ads.csv
```

CSV (UTF-8, 첫 줄은 머리글):

```
place_id,starts_at,ends_at,memo
3f2b...-uuid,2026-11-01T00:00:00+09:00,2026-12-01T00:00:00+09:00,광고주 A 11월
```

- `place_id`는 places.id(uuid)다. 시간대가 없는 시각은 Asia/Seoul로 본다. `ends_at` 시각은 포함하지 않는다.
- 장소가 places에 있고 status가 open인지, 기간이 맞는지(시작 < 끝, 끝이 지금보다 뒤), 그 장소에 active 광고가 이미 없는지,
  CSV 안에 같은 장소가 두 번 없는지 본다. **하나라도 틀리면 아무것도 넣지 않는다.**

## 장소 찾기

```
python -m ads.scripts.find_place "온도 커피" --category 카페
```

이름 일부(대소문자 무시)로 places를 찾아 place_id, 이름, 주소, status를 출력한다. `--category`와 `--limit`(기본 20)은 선택이다.
closed 장소도 나오니 등록에는 status가 open인 것만 쓴다. 읽기 전용이다.

## 내리기

```
python -m ads.scripts.deactivate <ad_id>
```

active를 false로 바꾼다. 집계 행은 남는다. 다시 걸려면 새로 등록한다(같은 장소에 active 광고는 하나).

## 집계 확인 (SQL)

노출(served_count)은 "광고 조회 응답에 실린 횟수"다. 화면에 실제로 보인 횟수가 아니라 많게 센다(docs/ads.md 9절).
날짜(stat_date)는 Asia/Seoul 기준이다.

진행 중인 광고:

```sql
SELECT id, place_id, starts_at, ends_at, memo FROM ads
WHERE active AND starts_at <= now() AND now() < ends_at
ORDER BY ends_at;
```

광고별 누적 노출, 클릭, 클릭률:

```sql
SELECT a.id, a.place_id, a.memo,
       COALESCE(SUM(s.served_count), 0) AS served,
       COALESCE(SUM(s.click_count), 0)  AS clicks,
       ROUND(COALESCE(SUM(s.click_count), 0)::numeric / NULLIF(SUM(s.served_count), 0), 4) AS ctr
FROM ads a LEFT JOIN ad_daily_stats s ON s.ad_id = a.id
GROUP BY a.id ORDER BY served DESC;
```

한 광고의 날짜별 추이(최근 30일):

```sql
SELECT stat_date, served_count, click_count FROM ad_daily_stats
WHERE ad_id = '<ad_id>' AND stat_date >= (now() AT TIME ZONE 'Asia/Seoul')::date - 30
ORDER BY stat_date;
```

어제(Asia/Seoul) 하루 합계:

```sql
SELECT SUM(served_count) AS served, SUM(click_count) AS clicks FROM ad_daily_stats
WHERE stat_date = (now() AT TIME ZONE 'Asia/Seoul')::date - 1;
```
