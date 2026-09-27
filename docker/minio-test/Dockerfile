# Test-only S3 fixture. MinIO no longer publishes the pinned Quay images, so
# build from its official release assets and verify the published SHA-256 values.
# This image is never used by production Compose.
FROM alpine:3.21@sha256:ce64758a109eb420d874a118f87920e625e12d3634e03b4a5573fd9f6e5d3507

ARG TARGETARCH
ARG MINIO_RELEASE=RELEASE.2024-11-07T00-52-20Z
ARG MC_RELEASE=RELEASE.2024-11-21T17-21-54Z

RUN set -eu; \
    apk add --no-cache ca-certificates curl; \
    case "$TARGETARCH" in \
      amd64) \
        minio_sha=c27873d791b56d33518de11f12c5bfae4be88ebac00e12c6dd0027b08123fd80; \
        mc_sha=0312010a9d0aa7a52b4dfb14330f289ee4e295def80b3a3f530d4f38c1b71da0;; \
      arm64) \
        minio_sha=4c5ed5a8563b92a15c41a1cb9b382c448a72dc09026faecb4afb3eb44f10375b; \
        mc_sha=a6b0b36ccd4674524674a032d10b1a474ffe4187e93d83f53560092c86c57ac4;; \
      *) echo "Unsupported MinIO fixture architecture: $TARGETARCH" >&2; exit 1;; \
    esac; \
    curl --fail --location --silent --show-error --retry 3 \
      "https://github.com/minio/minio/releases/download/${MINIO_RELEASE}/minio.linux-${TARGETARCH}.${MINIO_RELEASE}" \
      --output /usr/local/bin/minio; \
    echo "${minio_sha}  /usr/local/bin/minio" | sha256sum -c -; \
    curl --fail --location --silent --show-error --retry 3 \
      "https://github.com/minio/mc/releases/download/${MC_RELEASE}/mc.linux-${TARGETARCH}.${MC_RELEASE}" \
      --output /usr/local/bin/mc; \
    echo "${mc_sha}  /usr/local/bin/mc" | sha256sum -c -; \
    chmod 0755 /usr/local/bin/minio /usr/local/bin/mc
