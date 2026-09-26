#!/bin/sh
ulimit -c 0
crond -b -l 8 -L /proc/1/fd/1 -c /app/crontabs
exec "$@"
