#!/bin/sh
set -e

DB_HOST="${DB_HOST:-db}"

echo "[db-init] Waiting for Postgres at ${DB_HOST}:5432..."
until pg_isready -h "$DB_HOST" -p 5432 -U "$DB_ADMIN_USER"; do
  sleep 2
done

# Escape single quotes in the password (SQL standard: '' inside a literal)
ESCAPED_PW=$(printf '%s' "$POSTGRES_PASSWORD" | sed "s/'/''/g")

echo '[db-init] Creating perdiem role if not exists...'
ROLE_EXISTS=$(psql -h "$DB_HOST" -U "$DB_ADMIN_USER" -tAc \
  "SELECT 1 FROM pg_roles WHERE rolname='perdiem'")
if [ "$ROLE_EXISTS" != "1" ]; then
  psql -h "$DB_HOST" -U "$DB_ADMIN_USER" \
    -c "CREATE USER perdiem WITH PASSWORD '${ESCAPED_PW}'"
  echo '[db-init] Role perdiem created.'
else
  echo '[db-init] Role perdiem already exists, skipping.'
fi

echo '[db-init] Creating perdiem database if not exists...'
DB_EXISTS=$(psql -h "$DB_HOST" -U "$DB_ADMIN_USER" -tAc \
  "SELECT 1 FROM pg_database WHERE datname='perdiem'")
if [ "$DB_EXISTS" != "1" ]; then
  psql -h "$DB_HOST" -U "$DB_ADMIN_USER" \
    -c "CREATE DATABASE perdiem OWNER perdiem"
  echo '[db-init] Database perdiem created.'
else
  echo '[db-init] Database perdiem already exists, skipping.'
fi

echo '[db-init] Done.'
