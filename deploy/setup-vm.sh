#!/usr/bin/env bash
# Airlock — one-shot setup for a fresh Ubuntu 22.04/24.04 Vultr VM.
# Run as root:  bash setup-vm.sh [git-url] [branch]
set -euo pipefail

REPO_URL="${1:-https://github.com/YodHeVauHe/airlock.git}"
BRANCH="${2:-main}"
APP_DIR="/srv/airlock"

echo "==> installing docker"
if ! command -v docker >/dev/null; then
  apt-get update -y
  apt-get install -y ca-certificates curl git
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi
systemctl enable --now docker

echo "==> fetching airlock"
if [ ! -d "$APP_DIR" ]; then
  git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

echo "==> building the sandbox image (the disposable cell agent code runs in)"
docker build -t airlock-sandbox:latest ./sandbox

echo "==> configuring environment"
if [ ! -f .env ]; then
  cat > .env <<EOF
AIRLOCK_PUBLIC_URL=http://$(curl -s https://api.ipify.org)
AIRLOCK_INFERENCE_API_KEY=
AIRLOCK_INFERENCE_MODEL=
AIRLOCK_MOCK_LLM=1
EOF
  echo "    created .env — paste your Vultr Serverless Inference key, set AIRLOCK_MOCK_LLM=0"
fi

echo "==> starting control plane"
docker compose -f deploy/docker-compose.yml up -d --build

echo "==> waiting for health"
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1/api/health >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -fsS http://127.0.0.1/api/health && echo

IP=$(curl -s https://api.ipify.org || echo "YOUR_VM_IP")
echo
echo "Airlock is live:  http://$IP/"
echo "Torture chamber:  http://$IP/torture"
