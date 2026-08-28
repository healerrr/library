#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "错误：未找到 Docker，请先安装 Docker Engine 和 Docker Compose 插件。" >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "错误：未找到 docker compose 插件。" >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "错误：Docker 服务未运行，或当前用户没有访问 Docker 的权限。" >&2
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "已根据 .env.example 创建 .env"
fi

current_password=$(sed -n 's/^POSTGRES_PASSWORD=//p' .env | head -n 1)
case "$current_password" in
  ""|change-me|change-this-to-a-long-random-password)
    if command -v openssl >/dev/null 2>&1; then
      generated_password=$(openssl rand -hex 24)
    else
      generated_password=$(dd if=/dev/urandom bs=24 count=1 2>/dev/null | od -An -tx1 | tr -d ' \n')
    fi
    temporary_env=$(mktemp "${TMPDIR:-/tmp}/copyguard-env.XXXXXX")
    awk -v password="$generated_password" '
      BEGIN { password_written = 0 }
      /^POSTGRES_PASSWORD=/ {
        print "POSTGRES_PASSWORD=" password
        password_written = 1
        next
      }
      /^DATABASE_URL=.*change-me/ {
        print "DATABASE_URL="
        next
      }
      { print }
      END {
        if (!password_written) print "POSTGRES_PASSWORD=" password
      }
    ' .env > "$temporary_env"
    mv "$temporary_env" .env
    chmod 600 .env 2>/dev/null || true
    echo "已生成随机 PostgreSQL 密码并写入 .env"
    ;;
esac

docker compose config >/dev/null

if docker compose up --help 2>/dev/null | grep -q -- '--wait'; then
  docker compose up -d --build --remove-orphans --wait --wait-timeout 600
else
  docker compose up -d --build --remove-orphans
fi

docker compose ps

app_port=$(sed -n 's/^APP_PORT=//p' .env | head -n 1)
app_port=${app_port:-3000}
echo ""
echo "部署完成。请访问：http://<服务器IP>:${app_port}"
echo "查看日志：docker compose logs -f"
