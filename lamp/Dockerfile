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
RUN chmod +x /entrypoint.sh /cleanup.sh
# max-children bounds how many connections socat forks at once. A single xelatex
# peaks at ~580 MiB virtual / ~316 MiB resident, so on the 6 GiB vulnbox the
# worst case must stay well under RAM: 12 * ~316 MiB ~= 3.7 GiB. Combined with
# the per-process ulimit in entrypoint.sh (1 GiB address space) this keeps a
# flood of connections from exhausting host RAM and triggering the OOM killer.
CMD ["socat", "-6", "tcp-l:1337,fork,reuseaddr,max-children=12", "EXEC:/entrypoint.sh"]
