#!/usr/bin/env bash
# 새 DB에 장소 데이터를 넣는다(#168). 순서와 규칙은 deploy_rules.md 「장소 데이터 적재」와 공유본 README 그대로다.
#   ./load-places.sh staging /srv/pingo/data/places_1104          # 넣기
#   DRY_RUN=1 ./load-places.sh staging /srv/pingo/data/places_1104 # 경로와 건수만 확인
#   ./load-places.sh prod /srv/pingo/data/places_1104 boundaries   # 시·도 경계만(이미 도는 DB에 처음 넣을 때. 멱등, 장소는 건드리지 않는다, #1385)
# 데이터 폴더(공유본 두 개를 합친 것)는 저장소 밖, 서버의 /srv/pingo/data에 둔다. 구조:
#   <폴더>/서울/{음식점,카페,관광지,인허가_커버리지}, <폴더>/<지역>/{정예_음식점,정예_카페,정예_관광지,인허가_커버리지}
#   <폴더>/시도경계/{11,21,…,39}.json — 시·도 경계 17개. 화면 정본(frontend/src/features/map/regionBoundaries/)의 사본을 그대로 둔다.
#     로더가 파일 내용 해시를 코드의 기대값과 비교해 정본과 다르면 거절한다(places/boundaries.py, #1385).
# 새 DB라 인허가에 --close-missing을 쓰지 않는다(닫을 행이 없다). 마이그레이션(deploy.sh)을 먼저 한다.
set -euo pipefail
cd "$(dirname "$0")"
env_name=${1:?prod 또는 staging}
host_dir=${2:?데이터 폴더}
REGIONS=(대전 춘천 광주 대구 부산)
dry=()
[ "${DRY_RUN:-}" = 1 ] && dry=(--dry-run)

load() {
  echo "== places.load $*"
  docker compose run --rm --no-deps -T -v "$host_dir:/data:ro" "api-$env_name" python -m places.load "$@" "${dry[@]}"
}

S=/data
# 시·도 경계(#1385) — 지역 판정(places.api.sido_at, circle_outside_region)의 정본 표. 멱등이라 먼저 넣는다
# 데이터 폴더에 시도경계/가 없으면(옛 폴더) 경고만 하고 건너뛴다 — 장소 적재는 계속한다. `boundaries`만 요청했으면 중단한다
boundaries_loaded=1
if [ -d "$host_dir/시도경계" ]; then
  load boundaries --dir $S/시도경계
elif [ "${3:-}" = boundaries ]; then
  echo "중단: $host_dir/시도경계 폴더가 없다" >&2; exit 1
else
  boundaries_loaded=0
  echo "경고: $host_dir/시도경계 폴더가 없어 경계 적재를 건너뛴다" >&2
fi
[ "${3:-}" = boundaries ] && { echo "끝(시·도 경계만)."; exit 0; }
# 서울 정예(음식점 다음 카페 — 두 파일에 겹치는 곳을 카페로 둔다, #507)
load restaurants --authoritative --file $S/서울/음식점/final_restaurant_places_hotspot.csv --labels $S/서울/음식점/seoul_restaurant_labels_hotspot.json
load cafes --authoritative --file $S/서울/카페/cafe_seoul_curated.csv --labels $S/서울/카페/cafe_seoul_curated_labels.json
load tourapi --authoritative --file $S/서울/관광지/tourist_seoul_places.json --labels $S/서울/관광지/tourist_seoul_curated_labels.csv
# 서울 커버리지(인허가 파일 3개를 한 번에)
load permit --encoding cp949 \
  --file $S/서울/인허가_커버리지/식품_휴게음식점_서울특별시.csv \
  --file $S/서울/인허가_커버리지/식품_일반음식점_서울특별시.csv \
  --file $S/서울/인허가_커버리지/식품_제과점영업_서울특별시.csv
load restaurant-labels --file $S/서울/인허가_커버리지/permit_cover_labels.json

# 지역(v2)
for R in "${REGIONS[@]}"; do
  load restaurants --authoritative --all-regions --file $S/$R/정예_음식점/restaurant_${R}_curated.csv --labels $S/$R/정예_음식점/restaurant_${R}_curated_labels.json
  load cafes --authoritative --all-regions --file $S/$R/정예_카페/cafe_${R}_curated.csv --labels $S/$R/정예_카페/cafe_${R}_curated_labels.json
  load tourapi --authoritative --all-regions --file $S/$R/정예_관광지/tourist_${R}_curated_places.json --labels $S/$R/정예_관광지/tourist_${R}_curated_labels.csv
  load permit --encoding cp949 --all-regions \
    --file $S/$R/인허가_커버리지/식품_휴게음식점_${R}.csv \
    --file $S/$R/인허가_커버리지/식품_일반음식점_${R}.csv \
    --file $S/$R/인허가_커버리지/식품_제과점영업_${R}.csv
  load restaurant-labels --file $S/$R/인허가_커버리지/permit_cover_labels.json
done

# 영업시간(장소를 모두 넣은 뒤)
load place-hours --file $S/서울/음식점/seoul_restaurant_labels_hotspot.json
load place-hours --file $S/서울/카페/cafe_seoul_curated_labels.json
load place-hours --file $S/서울/관광지/tourist_seoul_closed_days.json
for R in "${REGIONS[@]}"; do
  load place-hours --all-regions --file $S/$R/정예_음식점/restaurant_${R}_curated_labels.json
  load place-hours --all-regions --file $S/$R/정예_카페/cafe_${R}_curated_labels.json
  load place-hours --all-regions --file $S/$R/정예_관광지/tourist_${R}_curated_labels.json
done
[ "$boundaries_loaded" = 1 ] || echo "경계 미적재 — 시·도 판정은 가장 가까운 장소 방식으로 동작한다(시도경계/를 두고 ./load-places.sh $env_name $host_dir boundaries)"
echo "끝. 마지막에 나온 [curated] 분류별 정예 수를 deploy_rules.md의 실측(정예 13,901곳)과 맞춰 본다."
