"""추천 탭 광고 상수(docs/ads.md 5절). 값을 바꾸면 명세 13절 표도 같이 고친다."""

AD_SLOTS = 2               # 한 번에 보여주는 광고 수 상한
AD_RADIUS_M = 5000         # 화면 중심에서의 반경(m). 이웃한 구까지 덮는 시작값(2026-10-19 결정, 실측 아님)
AD_STATS_TZ = "Asia/Seoul"  # 집계 날짜(ad_daily_stats.stat_date)를 자르는 기준 시간대
