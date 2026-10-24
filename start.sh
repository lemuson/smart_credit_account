#!/bin/sh
set -eu
cd "$(dirname "$0")"
# Never overwrite an existing backend environment.
if [ ! -f backend/.env ]; then
  umask 077
  if ! command -v openssl >/dev/null 2>&1; then
    echo 'Для создания секретов нужен openssl. Можно также создать backend/.env по backend/.env.example.' >&2
    exit 1
  fi
  db_secret=$(openssl rand -hex 32)
  jwt_secret=$(openssl rand -hex 48)
  printf 'POSTGRES_DB=credit\nPOSTGRES_USER=credit\nPOSTGRES_PASSWORD=%s\nJWT_SECRET=%s\n' "$db_secret" "$jwt_secret" > backend/.env
fi
docker compose up --build -d "$@"
printf '\nКредитный кабинет: http://localhost:%s\n' "${FRONTEND_PORT:-8080}"
