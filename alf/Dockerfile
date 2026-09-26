FROM faust.cs.fau.de:5000/alf_deps
# FROM alf_deps

WORKDIR /app/data
WORKDIR /app/db

WORKDIR /app/.flask_secret
WORKDIR /app

RUN adduser -D -H app \
	&& mkdir -p /app/crontabs \
	&& chown -R app:app /app/data /app/db /app/.flask_secret /app/crontabs
COPY --chown=app:app ./src ./src

RUN echo "*/3 * * * * /app/src/cleanup/cleanup.sh >> /proc/1/fd/1 2>&1" > /app/crontabs/app \
	&& chown app:app /app/crontabs/app \
	&& chmod 600 /app/crontabs/app

RUN echo "*/3 * * * * /app/src/cleanup/cleanup.sh >> /proc/1/fd/1 2>&1" >> /etc/crontabs/root

ENV PYTHONUNBUFFERED=1
#CMD ["python", "-m", "flask", "--debug", "--app", "/app/", "run", "--host=::", "--port=1986"]
ENTRYPOINT ["/app/src/entrypoint.sh"]
CMD ["gunicorn", \
     "-w", "4", \
     "--preload", \
     "-b", "[::]:1986", \
     "--worker-tmp-dir", "/dev/shm", \
     "src:create_app()"]

USER app
