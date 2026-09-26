#!/bin/sh
exec gunicorn --bind '[::]:1337' --workers 2 --threads 4 --access-logfile - --error-logfile - app:app
