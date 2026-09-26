FROM alpine

RUN apk add texlive-xetex \
    texmf-dist-latexextra \
    mysql-client \
	mariadb-connector-c \
    socat \
    coreutils \
    xxd

RUN mkdir -p /storage

WORKDIR /tmp
COPY entrypoint.sh /entrypoint.sh
COPY cleanup.sh /cleanup.sh
CMD ["socat", "-6", "tcp-l:1337,fork,reuseaddr", "EXEC:/entrypoint.sh"]
