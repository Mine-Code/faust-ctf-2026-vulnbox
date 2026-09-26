#!/bin/sh
set -e

# Filesystem cleanup
deleted=$(find /app/data -mindepth 1 -maxdepth 1 -type d -mmin +20 -print -exec rm -rf {} + | wc -l)
echo "Deleted $deleted dir(s)"

# DB cleanup
psql "$DB_URL" -v ON_ERROR_STOP=1 \
  -c "DELETE FROM public.user WHERE creation_date < NOW() - INTERVAL '20 minutes';"

