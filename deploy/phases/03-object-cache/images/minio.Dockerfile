# MinIO server, source-built (ADR-015). Upstream container registries are unreachable
# from this network; the binary is compiled from the upstream git tag
# RELEASE.2025-10-15T17-29-55Z (build: agentic/tmp/build-minio3.sh, recorded in the
# mission log) and verified by checksum below before being staged.
# Runtime: non-root, minimal alpine. MinIO needs only the binary + data volume.
FROM alpine:3.21
RUN apk add -q --no-cache ca-certificates && adduser -D -u 1000 minio
COPY minio /usr/bin/minio
# Checksum gate at build: refuses to package a binary that does not match the
# recorded sha256 of the compile output (recorded in the mission log).
ARG MINIO_SHA256
RUN [ "$MINIO_SHA256" != "" ] && echo "$MINIO_SHA256  /usr/bin/minio" | sha256sum -c -
USER 1000
EXPOSE 9000 9001
ENTRYPOINT ["minio"]
