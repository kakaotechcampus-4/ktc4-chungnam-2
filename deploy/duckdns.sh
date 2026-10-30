#!/usr/bin/env bash
# DuckDNS 주소가 서버 IP를 가리키게 한다(cron이 5분마다). 서버 IP가 고정(Elastic IP)이면 cron에서 빼도 된다.
# 토큰은 ../secrets/duckdns_token(권한 600)에만 둔다. 저장소, 채팅에 남기지 않는다.
set -euo pipefail
cd "$(dirname "$0")"
token=$(cat ../secrets/duckdns_token)
curl -fsS "https://www.duckdns.org/update?domains=ktc-pingopingo&token=${token}&ip=" -o /dev/null
