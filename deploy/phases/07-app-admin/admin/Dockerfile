# adminService image — Phase 7f (ADR-013 fresh rebuild).
#
# Build context is the PHASE DIRECTORY (established pattern; the host daemon cannot
# resolve the k3d registry alias — G0.3):
#   docker build -f deploy/phases/07-app-admin/admin/Dockerfile \
#     -t localhost:35000/mission/nagar-admin-service:phase7f-1 deploy/phases/07-app-admin
#
# Hardened per SECURITY §5/§7: pinned base, non-root uid, read-only-root compatible,
# tests NOT shipped. Port 4001 is baked into the CMD — no *_PORT env read exists
# anywhere in this image, so the 7e service-link env injection class (OPERATIONS
# §12.28) cannot touch it.
FROM python:3.12-slim

COPY admin/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --requirement /app/requirements.txt \
    && adduser --disabled-password --uid 1000 --gecos "" nagar

COPY --chown=1000:1000 admin/app.py /app/

USER 1000
WORKDIR /app
ENV PYTHONUNBUFFERED=1
EXPOSE 4001
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "4001"]
