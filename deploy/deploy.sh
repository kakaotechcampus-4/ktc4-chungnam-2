#!/usr/bin/env bash
# 한 환경을 고른 이미지 태그로 올린다(#168). 롤백도 같은 명령으로 이전 태그를 고른다.
#   ./deploy.sh prod v0.2.0
#   ./deploy.sh staging develop
# 순서: 이미지 받기 → (운영이면) DB 백업 → 새 이미지로 마이그레이션 → 교체 → 건강 확인 → 배포 뒤 점검. 어느 쪽이든 실패하면 이전 태그로 되돌리고,
# 되돌린 뒤에도 같은 점검을 해서 이전 컨테이너가 건강한지 확인한다(#1214).
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

# API 컨테이너가 healthy가 될 때까지 기다린다(최대 90초). 된 뒤에 0, 못 되면 1.
wait_healthy() {
  local status
  for _ in $(seq 1 45); do
    status=$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q "$api")" 2>/dev/null || echo none)
    [ "$status" = healthy ] && return 0
    sleep 2
  done
  return 1
}

# 배포 뒤 점검(#1214) — healthy 하나로는 모르는 것을 본다. 하나라도 실패하면 1을 돌려 호출한 쪽이 되돌린다.
#  · API가 /health에 200으로 답한다(폴러 상태 포함, #1205 — 컨테이너 안에서 python으로 부른다)
#  · 웹 컨테이너가 화면을 200으로 낸다(busybox wget이나 curl이 있어야 한다 — 둘 다 없으면 건너뛰고 경고만 남긴다, 이미지를 바꾸면 이 줄도 고친다)
# 로그인·DB 쓰기·SSE 연결 확인은 점검 전용 엔드포인트가 필요해 아직 넣지 않았다(#1214에 남은 일로 적었다).
verify() {
  log "배포 뒤 점검"
  if ! docker compose exec -T "$api" python -c "import sys,urllib.request as u; sys.exit(0 if u.urlopen('http://127.0.0.1:8000/health', timeout=5).status == 200 else 1)"; then
    log "점검 실패: API /health"
    return 1
  fi
  if docker compose exec -T "$web" sh -c 'command -v wget >/dev/null'; then
    docker compose exec -T "$web" wget -q -T 5 -O /dev/null http://127.0.0.1/ || { log "점검 실패: 웹 화면"; return 1; }
  elif docker compose exec -T "$web" sh -c 'command -v curl >/dev/null'; then
    docker compose exec -T "$web" curl -fsS -m 5 -o /dev/null http://127.0.0.1/ || { log "점검 실패: 웹 화면"; return 1; }
  else
    log "경고: 웹 컨테이너에 wget·curl이 없어 화면 점검을 건너뛴다"
  fi
  log "점검 통과"
}

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
if wait_healthy && verify; then
  log "완료 ($tag)"
  echo "$(date '+%F %T') $env_name $prev -> $tag ok" >> deploy-history.log
  exit 0
fi

log "건강 확인 또는 배포 뒤 점검 실패 — $prev로 되돌린다"
export "$var=$prev"
sed -i "s/^$var=.*/$var=$prev/" .env
docker compose up -d --no-deps "$api" "$web"
if wait_healthy && verify; then
  echo "$(date '+%F %T') $env_name $prev -> $tag FAILED, rolled back (이전 태그 정상)" >> deploy-history.log
else
  log "경고: 되돌린 $prev도 건강하지 않다 — 사람이 바로 봐야 한다"
  echo "$(date '+%F %T') $env_name $prev -> $tag FAILED, rolled back, 이전 태그도 비정상" >> deploy-history.log
fi
exit 1
