#!/usr/bin/env bash
# 돌고 있는 API 컨테이너 안에서 명령 하나를 돌린다(정기 정리, 관찰 tick 등).
#   ./run.sh prod python -m maintenance.run --dry-run
set -euo pipefail
cd "$(dirname "$0")"
env_name=${1:?prod 또는 staging}
shift
docker compose exec -T "api-$env_name" "$@"
