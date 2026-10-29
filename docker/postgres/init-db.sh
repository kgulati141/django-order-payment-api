
#!/bin/sh
set -eu

psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=app_user="$DB_USER" \
  --set=app_password="$DB_PASSWORD" \
  --set=app_db="$DB_NAME" <<'SQL'
CREATE ROLE :"app_user" WITH LOGIN PASSWORD :'app_password';
CREATE DATABASE :"app_db" OWNER :"app_user";
SQL
