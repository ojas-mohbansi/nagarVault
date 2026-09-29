# nagar-ollama-models payload image (ADR-010) — Phase 6.
#
# Build context MUST be the directory containing `.ollama/` (the two mission models staged by
# the operator) and `models-manifest.sha256`. The build fails loudly if any blob's checksum
# drifts, so the image can only ever contain exactly the bytes the manifest in git declares.
#
#   docker build -f deploy/phases/06-vector-llm/models/Dockerfile \
#     -t localhost:35000/mission/ollama-models:phase6-1 deploy/phases/06-vector-llm/models
#
# (the operator copies the staged payload into that directory first — see the mission log).
#
# Why an image and not a tarball on a PVC: the tarball would itself need a place to live that
# the cluster can read; the registry is that place, it is versioned, and `docker push` already
# has retry/verify semantics here. The Job's contract stays exactly ADR-010: verify SHA-256,
# restore, never pull from the internet.
FROM alpine:3.20
COPY models-manifest.sha256 /payload/models-manifest.sha256
COPY .ollama /payload/.ollama
# Checksum gate at build time: the image cannot exist unless every blob matches the manifest
# that git carries. The manifest's paths are RELATIVE TO .ollama/models (that is the directory
# the operator hashes from), so the check runs from there and references the manifest by its
# absolute path. The `*` prefix on each entry is sha256sum's binary-mode marker, accepted by
# busybox's implementation.
RUN cd /payload/.ollama/models \
    && sha256sum -c /payload/models-manifest.sha256 \
    && echo "MODEL-PAYLOAD-VERIFIED: $(grep -c . /payload/models-manifest.sha256) blobs OK"
