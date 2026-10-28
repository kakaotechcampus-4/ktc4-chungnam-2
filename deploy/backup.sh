#!/usr/bin/env bash
# 한 환경의 DB를 덤프한다(배포 직전, 그리고 cron이 하루 한 번). 14일 지난 덤프는 지운다.
#   ./backup.sh prod
# DATABASE_URL은 env/<환경>.env에서 읽는다 — 서버 안 DB든 RDS든 같은 명령이다.
# 서버 안 DB를 쓰는 동안은 덤프도 같은 디스크에 있다(서버가 사라지면 같이 사라진다). deploy_rules.md 「타협」.
set -euo pipefail
cd "$(dirname "$0")"
env_name=${1:?prod 또는 staging}
url=$(grep '^DATABASE_URL=' "env/$env_name.env" | cut -d= -f2-)
mkdir -p ../backups
out="../backups/pingo_${env_name}-$(date +%F-%H%M).dump"
docker run --rm --network pingo_default postgis/postgis:17-3.5-alpine pg_dump -Fc "$url" > "$out"
find ../backups -name "pingo_${env_name}-*.dump" -mtime +14 -delete
echo "$out"
