FROM python:3.12-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py cleanup.py ./
COPY templates ./templates
COPY srv/www ./srv/www
COPY entrypoint.sh cleanup.sh /usr/local/bin/

RUN mkdir -p /storage && chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/cleanup.sh

EXPOSE 1337
CMD ["/usr/local/bin/entrypoint.sh"]
