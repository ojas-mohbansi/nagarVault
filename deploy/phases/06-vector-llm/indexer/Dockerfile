# schemaIndexer image — Phase 6 (ADR-013 rebuild).
#
# BUILD CONTEXT IS THE PHASE DIRECTORY (not this file's directory):
#   docker build -f deploy/phases/06-vector-llm/indexer/Dockerfile \
#     -t localhost:35000/mission/schema-indexer:phase6-1 deploy/phases/06-vector-llm
#
# Base image note: FROM python:3.12-slim (Docker Hub) because the build host's daemon cannot
# resolve the k3d registry alias (G0.3 note 1); the built image is retagged and pushed into the
# local registry, and the CLUSTER only ever pulls mission/schema-indexer from there (I-11) —
# the same build-time/runtime split as every source-built image before it (ADR-015).
#
# The schema corpus is baked in at /app/schema_docs.json, so the indexer and git agree by
# construction and a corpus change forces a new image digest (new rollout, I-5).
#
# PSS restricted: runs as uid 10001, no capabilities; the pod mounts a tmp emptyDir at /tmp
# (uvicorn temp state) and the PVC-free root filesystem is read-only at the pod level.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TMPDIR=/tmp \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY indexer/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt \
    && adduser --uid 10001 --disabled-password --gecos "" indexer

COPY indexer/index.py /app/index.py
COPY schema/schema_docs.json /app/schema_docs.json

USER 10001
WORKDIR /app
EXPOSE 4005
CMD ["python", "/app/index.py"]
