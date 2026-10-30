#!/usr/bin/env bash
# RDS 첫 설정(#873) — 사람이 Session Manager에서 한 번만 돌린다. 마스터 비밀번호가 필요해 워크플로로 돌리지 않는다
# (비밀번호를 GitHub에 넣지 않는다).
#   cd /srv/pingo/deploy && ./rds-setup.sh
# 하는 일: 마스터 비밀번호를 물어(화면에 안 보인다) rds/setup.sql을 돌린다 — 환경별 앱 계정, DB pingo_staging, 확장 postgis·pg_trgm.
# 앱 계정 비밀번호는 여기서 만들어 env/<환경>.env의 RDS_DATABASE_URL에만 적는다. 어떤 비밀번호도 출력하지 않는다.
# 그다음은 move-to-rds.sh(워크플로 move-to-rds)가 RDS_DATABASE_URL로 옮긴다.
set -euo pipefail
cd "$(dirname "$0")"

rds_host=$(grep '^RDS_HOST=' .env | cut -d= -f2- || true)
[ -n "$rds_host" ] || { echo ".env에 RDS_HOST=<RDS 엔드포인트>를 먼저 적는다(.env.example)" >&2; exit 2; }
for env_name in prod staging; do
  if grep -q '^RDS_DATABASE_URL=' "env/$env_name.env"; then
    echo "env/$env_name.env에 RDS_DATABASE_URL이 이미 있다 — 첫 설정은 이미 했다" >&2
    exit 1
  fi
done

read -rsp "RDS 마스터(pingo_admin) 비밀번호 (Secrets Manager → 보안 암호 값 검색): " PGPASSWORD
echo
export PGPASSWORD
# URL에 그대로 넣을 수 있게 16진수만 쓴다(퍼센트 인코딩이 필요 없다)
PINGO_PROD_APP_PW=$(openssl rand -hex 24)
PINGO_STAGING_APP_PW=$(openssl rand -hex 24)
export PINGO_PROD_APP_PW PINGO_STAGING_APP_PW

docker run --rm -i -e PGPASSWORD -e PINGO_PROD_APP_PW -e PINGO_STAGING_APP_PW -v "$PWD/rds:/rds:ro" \
  postgis/postgis:17-3.5-alpine \
  psql "host=$rds_host port=5432 user=pingo_admin dbname=pingo_prod sslmode=require" -X -f /rds/setup.sql

umask 077
echo "RDS_DATABASE_URL=postgresql://pingo_prod_app:$PINGO_PROD_APP_PW@$rds_host:5432/pingo_prod?sslmode=require" >> env/prod.env
echo "RDS_DATABASE_URL=postgresql://pingo_staging_app:$PINGO_STAGING_APP_PW@$rds_host:5432/pingo_staging?sslmode=require" >> env/staging.env
unset PGPASSWORD PINGO_PROD_APP_PW PINGO_STAGING_APP_PW
echo "첫 설정 완료 — env/prod.env, env/staging.env에 RDS_DATABASE_URL을 적었다. 다음: 워크플로 move-to-rds(스테이징 → 운영)"
