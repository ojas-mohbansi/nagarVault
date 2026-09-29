# enrichWorker image — Phase 7c (ADR-013 fresh rebuild).
#
# Build context is the PHASE DIRECTORY (established pattern; G0.3 daemon alias limitation):
#   docker build -f deploy/phases/07-app-worker/worker/Dockerfile \
#     -t localhost:35000/mission/nagar-enrich-worker:phase7c-1 deploy/phases/07-app-worker
#
# No HTTP port: pure consumer process (uvicorn's graceful-shutdown pattern doesn't apply).
# Tests NOT shipped; secrets via env (I-3).
FROM python:3.12-slim

COPY worker/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --requirement /app/requirements.txt \
    && adduser --disabled-password --uid 1000 --gecos "" nagar

COPY --chown=1000:1000 worker/enrich.py /app/

USER 1000
WORKDIR /app
ENV PYTHONUNBUFFERED=1
CMD ["python", "enrich.py"]
