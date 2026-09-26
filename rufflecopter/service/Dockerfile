FROM faust.cs.fau.de:5000/rufflecopter_deps as build
WORKDIR /build
COPY Cargo.toml .
COPY src src
RUN cargo build --release --offline

RUN mkdir /dependencies
RUN ldd target/release/rufflecopter | awk '$1 ~ /^\// {print $1} $2 == "=>" {print $3}' | xargs tar hc | tar xC /dependencies


FROM scratch

WORKDIR /srv/rufflecopter

COPY server.swf .
COPY content ./content
COPY --from=build /dependencies /
COPY --from=build /build/target/release/rufflecopter .

ENV TERM=xterm-256color

CMD ["./rufflecopter"]
