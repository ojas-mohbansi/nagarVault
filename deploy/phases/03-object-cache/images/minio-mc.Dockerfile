# mc client, source-built (ADR-015). Binary compiled from upstream git tag
# RELEASE.2025-08-13T08-35-41Z (agentic/tmp/build-minio3.sh); checksum-gated at build.
FROM alpine:3.21
RUN apk add -q --no-cache ca-certificates && adduser -D -u 1000 mc
COPY mc /usr/bin/mc
ARG MC_SHA256
RUN [ "$MC_SHA256" != "" ] && echo "$MC_SHA256  /usr/bin/mc" | sha256sum -c -
USER 1000
ENTRYPOINT ["mc"]
