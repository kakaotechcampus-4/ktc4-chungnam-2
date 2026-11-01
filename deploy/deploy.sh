#!/usr/bin/env bash
# 한 환경을 고른 이미지 태그로 올린다(#168). 롤백도 같은 명령으로 이전 태그를 고른다.
#   ./deploy.sh prod v0.2.0
#   ./deploy.sh staging develop
# 순서: 이미지 받기 → (운영이면) DB 백업 → 새 이미지로 마이그레이션 → 교체 → 건강 확인. 건강 확인에 실패하면 이전 태그로 되돌린다.
# 스키마는 expand/contract로 바꾸므로 이전 태그의 코드도 새 스키마에서 돈다(deploy_rules.md 「스키마를 바꿀 때」).
set -euo pipefail
cd "$(dirname "$0")"

usage() { echo "사용: $0 <prod|staging> <이미지 태그>" >&2; exit 2; }
[ $# -eq 2 ] || usage
env_name=$1
tag=$2
case "$env_name" in
  prod) var=PROD_TAG ;;
  staging) var=STAGING_TAG ;;
  *) usage ;;
esac
api="api-$env_name"
web="web-$env_name"

exec 9>"/tmp/pingo-deploy-$env_name.lock"
flock -n 9 || { echo "$env_name 배포가 이미 진행 중이다" >&2; exit 1; }

prev=$(grep "^$var=" .env | cut -d= -f2-)
log() { echo "[$(date '+%F %T')] $env_name: $*"; }

log "$prev → $tag 시작"
export "$var=$tag"

log "이미지 받기"
docker compose pull --quiet "$api" "$web"

if [ "$env_name" = prod ]; then
  log "DB 백업"
  ./backup.sh prod
fi

log "마이그레이션"
docker compose run --rm --no-deps -T "$api" python -m alembic upgrade head < /dev/null

log "교체"
sed -i "s/^$var=.*/$var=$tag/" .env
docker compose up -d --no-deps "$api" "$web"

log "건강 확인"
for _ in $(seq 1 45); do
  status=$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q "$api")" 2>/dev/null || echo none)
  if [ "$status" = healthy ]; then
    log "완료 ($tag)"
    echo "$(date '+%F %T') $env_name $prev -> $tag ok" >> deploy-history.log
    exit 0
  fi
  sleep 2
done

log "건강 확인 실패 — $prev로 되돌린다"
echo "$(date '+%F %T') $env_name $prev -> $tag FAILED, rolled back" >> deploy-history.log
export "$var=$prev"
sed -i "s/^$var=.*/$var=$prev/" .env
docker compose up -d --no-deps "$api" "$web"
exit 1
