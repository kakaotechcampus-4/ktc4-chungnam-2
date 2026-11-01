#!/usr/bin/env bash
# 배포할 커밋의 deploy/ 파일을 받아 이 폴더에 맞춘다(#168). 저장소가 public이라 인증 없이 받는다.
#   ./sync.sh <커밋 sha 또는 태그>
# 서버에만 있는 것(.env, env/*.env, deploy-history.log)은 저장소에 없으므로 그대로 남는다.
# 돌고 있는 스크립트를 제자리에서 덮어쓰지 않게 파일을 지우고 새로 만든다(--remove-destination).
set -euo pipefail
ref=${1:?커밋 sha 또는 태그}
[[ "$ref" =~ ^[0-9A-Za-z._-]+$ ]] || { echo "ref 형식이 이상하다: $ref" >&2; exit 2; }
dir=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

curl -fsSL "https://github.com/kakaotechcampus-4/ktc4-chungnam-2/archive/$ref.tar.gz" \
  | tar -xz -C "$tmp" --strip-components=1 --wildcards '*/deploy/*'

before=$(sha256sum "$dir/Caddyfile" 2>/dev/null || true)
cp -a --remove-destination "$tmp/deploy/." "$dir/"
chmod +x "$dir"/*.sh
after=$(sha256sum "$dir/Caddyfile")

# 앞단 설정이 바뀌었으면 끊김 없이 다시 읽힌다
if [ "$before" != "$after" ] && [ -n "$(cd "$dir" && docker compose ps -q edge 2>/dev/null)" ]; then
  (cd "$dir" && docker compose exec -T edge caddy reload --config /etc/caddy/Caddyfile)
fi
echo "deploy 파일을 $ref에 맞췄다"
