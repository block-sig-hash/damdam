ARG WALG_VERSION=v3.0.8
ARG WALG_COMMIT=f81943e64bdf97aa66f6c52fec55114703f97af7

FROM --platform=$BUILDPLATFORM golang:1.25-alpine AS walg-builder
ARG WALG_VERSION
ARG WALG_COMMIT
RUN apk add --no-cache git
WORKDIR /src
RUN git clone --branch "${WALG_VERSION}" --depth 1 https://github.com/wal-g/wal-g.git .
ARG TARGETOS
ARG TARGETARCH
# WAL-G v3.0.8 imports Go 1.25's experimental encoding/json/v2 package.
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    test "$(git rev-parse HEAD)" = "${WALG_COMMIT}" \
    && cd main/pg \
    && CGO_ENABLED=0 GOEXPERIMENT=jsonv2 GOOS="${TARGETOS}" GOARCH="${TARGETARCH}" \
      go build -mod=mod -tags "" -o wal-g \
      -ldflags "-s -w \
      -X github.com/wal-g/wal-g/cmd/pg.gitRevision=${WALG_COMMIT} \
      -X github.com/wal-g/wal-g/cmd/pg.walgVersion=${WALG_VERSION}" \
    && cd ../.. \
    && test -s ./main/pg/wal-g

FROM postgres:16-alpine
RUN apk add --no-cache ca-certificates coreutils
COPY --from=walg-builder /src/main/pg/wal-g /usr/local/bin/wal-g
COPY docker/postgres-walg/backup-loop.sh /usr/local/bin/walg-backup-loop
COPY docker/postgres-walg/restore.sh /usr/local/bin/walg-restore
RUN chmod 0755 \
    /usr/local/bin/wal-g \
    /usr/local/bin/walg-backup-loop \
    /usr/local/bin/walg-restore
