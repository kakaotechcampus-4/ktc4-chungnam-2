#!/usr/bin/env bash
# 서버를 처음 한 번 준비한다(#168). sudo로 돌린다: sudo bash bootstrap.sh <배포 사용자> [ECR 레지스트리 주소]
# Docker와 compose 플러그인, cron, 시간대, 스왑, 폴더를 맞춘다. Ubuntu와 Amazon Linux 2023을 지원한다.
# ECR 주소를 주면 docker가 서버 역할(인스턴스 프로필)로 ECR에서 이미지를 받게 한다(ecr-login 도우미, 저장해 둔 비밀 없음).
set -euo pipefail
user=${1:?배포 사용자 이름(예: ubuntu, ec2-user)}
registry=${2:-}

if command -v apt-get >/dev/null; then
  apt-get update -y
  # Ubuntu 패키지로 맞춘다(ecr-login 도우미가 docker.io에 기대므로 같은 계열로 compose 플러그인도 받는다)
  DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl cron \
    docker.io docker-compose-v2 amazon-ecr-credential-helper
elif command -v dnf >/dev/null; then
  dnf install -y docker cronie
  systemctl enable --now crond
  if ! docker compose version >/dev/null 2>&1; then
    mkdir -p /usr/local/lib/docker/cli-plugins
    arch=$(uname -m)
    curl -fsSL "https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-${arch}" \
      -o /usr/local/lib/docker/cli-plugins/docker-compose
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
  fi
else
  echo "apt-get이나 dnf가 있는 서버만 지원한다" >&2
  exit 1
fi

systemctl enable --now docker
usermod -aG docker "$user"
timedatectl set-timezone Asia/Seoul || true

# 4GB 서버라 이미지 받기나 적재 중 메모리가 모자라지 않게 2GB 스왑을 둔다
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

if [ -n "$registry" ]; then
  home=$(getent passwd "$user" | cut -d: -f6)
  mkdir -p "$home/.docker"
  printf '{\n  "credHelpers": {\n    "%s": "ecr-login"\n  }\n}\n' "$registry" > "$home/.docker/config.json"
  chown -R "$user":"$user" "$home/.docker"
fi

mkdir -p /srv/pingo/{deploy/env,data,backups,logs,secrets}
chown -R "$user":"$user" /srv/pingo
chmod 700 /srv/pingo/secrets /srv/pingo/deploy/env
echo "준비 끝. $user로 다시 로그인하면 docker 명령을 쓸 수 있다."
