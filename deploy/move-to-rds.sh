#!/usr/bin/env bash
# 한 환경의 DB를 서버 안 컨테이너에서 RDS로 옮긴다(#873). 워크플로 move-to-rds가 부른다. 스테이징 먼저, 그다음 운영.
#   ./move-to-rds.sh staging move       쓰기 멈춤 → 덤프 → RDS에 복원 → 행 수 대조 → DATABASE_URL 교체 → 재시작 → 건강 확인
#   ./move-to-rds.sh staging rollback   DATABASE_URL을 옮기기 전 값으로 되돌리고 재시작한다(옮긴 뒤 RDS에 쓴 데이터는 따라오지 않는다)
#   ./move-to-rds.sh finish             두 환경이 모두 RDS면 서버 안 DB 컨테이너를 멈추고 COMPOSE_FILE에서 뺀다(볼륨은 남긴다)
# 미리 할 것: rds-setup.sh(사람이 한 번) — env/<환경>.env에 RDS_DATABASE_URL이 있어야 한다.
# 실패하면 바꾼 것이 없는 상태로 API를 다시 올리고 멈춘다. 접속 문자열과 비밀번호는 출력하지 않는다(컨테이너에 환경 변수로만 넘긴다).
set -euo pipefail
cd "$(dirname "$0")"

PG_IMAGE=postgis/postgis:17-3.5-alpine
log() { echo "[$(date '+%F %T')] ${env_name:-all}: $*"; }
url_of() { grep "^$1=" "env/$env_name.env" | tail -n1 | cut -d= -f2-; }
# 접속 문자열은 PGURL 환경 변수로만 넘긴다(명령 인자와 로그에 남지 않게)
pg() { local url=$1; shift; PGURL=$url docker run --rm -i -e PGURL --network pingo_default -v "$PWD/../backups:/backups" "$PG_IMAGE" "$@"; }

# 표마다 행 수(공개 스키마, PostGIS의 spatial_ref_sys 제외). 옮기기 전후를 그대로 비교한다
COUNT_SQL="select table_name || '=' || (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from public.%I', table_name), false, true, '')))[1]::text
from information_schema.tables where table_schema = 'public' and table_type = 'BASE TABLE' and table_name <> 'spatial_ref_sys' order by 1"
counts() { pg "$1" sh -c 'psql "$PGURL" -X -tA -c "$0"' "$COUNT_SQL"; }

wait_healthy() {
  for _ in $(seq 1 45); do
    status=$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q "api-$env_name")" 2>/dev/null || echo none)
    [ "$status" = healthy ] && return 0
    sleep 2
  done
  return 1
}

restart_api() { docker compose up -d --no-deps --force-recreate "api-$env_name"; }

transfer() {
  # 덤프 → 복원 → 행 수 대조. move가 별도 프로세스(`$0 <환경> _transfer`)로 부른다 — 실패는 종료 코드로만 알린다(set -e가 그대로 선다)
  local old new dump name before after
  old=$(url_of DATABASE_URL)
  new=$(url_of RDS_DATABASE_URL)

  log "덤프"
  dump=$(./backup.sh "$env_name" | tail -n1)
  name=$(basename "$dump")

  log "RDS에 복원"
  # 확장(postgis, pg_trgm)은 rds-setup이 만들었고 앱 계정은 확장을 만들 수 없어 목록에서 뺀다. PostGIS의 spatial_ref_sys도
  # 확장 것이라 뺀다(앱 계정은 쓸 권한이 없다). 소유자와 권한은 복원하는 앱 계정의 것이 된다
  pg "$new" sh -c 'pg_restore -l "/backups/$0" | grep -v -e " EXTENSION " -e "spatial_ref_sys" > /tmp/list &&
    pg_restore --use-list=/tmp/list --no-owner --no-privileges --no-comments --exit-on-error --single-transaction -d "$PGURL" "/backups/$0"' "$name"

  log "행 수 대조"
  before=$(counts "$old")
  after=$(counts "$new")
  if [ "$before" != "$after" ]; then
    diff <(echo "$before") <(echo "$after") || true
    log "행 수가 다르다"
    exit 1
  fi
  log "표 $(echo "$before" | wc -l)개 행 수가 같다 ($dump)"
}

move() {
  local env_file="env/$env_name.env" backup="env/$env_name.env.before-rds"
  local old new
  old=$(url_of DATABASE_URL)
  new=$(url_of RDS_DATABASE_URL)
  [ -n "$new" ] || { log "RDS_DATABASE_URL이 없다 — rds-setup.sh를 먼저 돌린다"; exit 2; }
  [[ "$new" == *sslmode=require* ]] || { log "RDS_DATABASE_URL에 sslmode=require가 없다(RDS는 SSL만 받는다)"; exit 2; }
  [[ "$old" == *@db:* ]] || { log "DATABASE_URL이 이미 서버 안 DB가 아니다 — 이미 옮겼다"; exit 1; }

  exec 9>"/tmp/pingo-deploy-$env_name.lock"   # deploy.sh와 같은 자물쇠 — 옮기는 동안 배포가 끼어들지 않는다
  flock -n 9 || { log "배포가 진행 중이다"; exit 1; }

  log "RDS 대상이 비어 있는지 확인"
  [ "$(pg "$new" sh -c 'psql "$PGURL" -X -tA -c "select to_regclass('"'public.alembic_version'"') is null"')" = t ] \
    || { log "RDS의 이 DB에 이미 테이블이 있다 — 덮어쓰지 않는다"; exit 1; }

  log "쓰기 멈춤(API 정지) — 여기부터 이 환경은 잠깐 열리지 않는다"
  docker compose stop "api-$env_name"
  if ! "$0" "$env_name" _transfer; then
    # 복원은 단일 트랜잭션이라 복원 중 실패면 RDS는 비어 있다. 복원 뒤 행 수 대조에서 실패했으면 테이블이 남는다 —
    # 다시 옮기기 전에 그 앱 계정으로 `DROP OWNED BY pingo_<환경>_app;`(확장은 마스터 것이라 남는다)
    log "실패 — DATABASE_URL은 그대로 두고 API를 다시 올린다(deploy_rules.md 「RDS로 옮기기」의 실패했을 때)"
    restart_api
    echo "$(date '+%F %T') $env_name db -> rds FAILED before switch" >> deploy-history.log
    exit 1
  fi

  log "DATABASE_URL 교체"
  cp -p "$env_file" "$backup"
  { grep -v '^DATABASE_URL=' "$backup"; echo "DATABASE_URL=$new"; } > "$env_file"
  restart_api
  if wait_healthy; then
    log "완료 — RDS로 돈다(되돌리기: ./move-to-rds.sh $env_name rollback)"
    # 덤프 경로는 transfer(별도 프로세스)의 로그에 있다 — 여기서는 모른다
    echo "$(date '+%F %T') $env_name db -> rds ok" >> deploy-history.log
  else
    log "건강 확인 실패 — 옮기기 전으로 되돌린다"
    cp -p "$backup" "$env_file"
    restart_api
    echo "$(date '+%F %T') $env_name db -> rds FAILED, rolled back" >> deploy-history.log
    exit 1
  fi
}

rollback() {
  local env_file="env/$env_name.env" backup="env/$env_name.env.before-rds"
  [ -f "$backup" ] || { log "$backup이 없다 — 옮긴 적이 없다"; exit 1; }
  # finish로 멈췄으면 다시 켜고 compose가 다시 보게 한다
  sed -i 's/^COMPOSE_FILE=compose.yml$/COMPOSE_FILE=compose.yml:compose.db.yml/' .env
  docker compose up -d db
  cp -p "$backup" "$env_file"
  restart_api
  wait_healthy || { log "되돌린 뒤 건강 확인 실패"; exit 1; }
  log "서버 안 DB로 되돌렸다. 옮긴 뒤 RDS에 쓴 데이터는 따라오지 않는다"
  echo "$(date '+%F %T') $env_name rds -> db rollback" >> deploy-history.log
}

finish() {
  for env_name in prod staging; do
    [[ "$(url_of DATABASE_URL)" != *@db:* ]] || { log "아직 서버 안 DB를 쓴다 — 먼저 옮긴다"; exit 1; }
  done
  env_name=""
  grep -q '^COMPOSE_FILE=compose.yml:compose.db.yml$' .env || { log "COMPOSE_FILE에 compose.db.yml이 없다 — 이미 마무리했다"; exit 0; }
  log "서버 안 DB 컨테이너를 멈춘다(볼륨 pgdata는 남긴다 — 11/20까지 되돌리기용)"
  docker compose -f compose.yml -f compose.db.yml stop db
  sed -i 's/^COMPOSE_FILE=compose.yml:compose.db.yml$/COMPOSE_FILE=compose.yml/' .env
  echo "$(date '+%F %T') db container stopped, COMPOSE_FILE=compose.yml" >> deploy-history.log
  log "마무리 완료"
}

case "${1:-}" in
  finish) env_name=""; finish ;;
  prod|staging)
    env_name=$1
    case "${2:-}" in
      move) move ;;
      _transfer) transfer ;;   # move 안에서만 부른다
      rollback) rollback ;;
      *) echo "사용: $0 <prod|staging> <move|rollback> | $0 finish" >&2; exit 2 ;;
    esac ;;
  *) echo "사용: $0 <prod|staging> <move|rollback> | $0 finish" >&2; exit 2 ;;
esac
