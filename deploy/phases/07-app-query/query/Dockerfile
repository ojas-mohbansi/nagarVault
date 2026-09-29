# queryService image — Phase 7b (ADR-013 fresh rebuild).
#
# Build context is the PHASE DIRECTORY (established pattern; the host daemon cannot resolve
# the k3d registry alias — G0.3):
#   docker build -f deploy/phases/07-app-query/query/Dockerfile \
#     -t localhost:35000/mission/nagar-query-service:phase7b-1 deploy/phases/07-app-query
#
# Hardened per SECURITY §5/§7: pinned base, non-root uid, read-only-root compatible,
# tests NOT shipped.
FROM python:3.12-slim

COPY query/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --requirement /app/requirements.txt \
    && adduser --disabled-password --uid 1000 --gecos "" nagar

COPY --chown=1000:1000 query/app.py /app/

USER 1000
WORKDIR /app
ENV PYTHONUNBUFFERED=1
EXPOSE 4003
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "4003"]
