# slmService image — Phase 7d (ADR-013 fresh rebuild).
#
# Build context is the PHASE DIRECTORY (established pattern; G0.3 daemon alias limitation):
#   docker build -f deploy/phases/07-app-slm/slm/Dockerfile \
#     -t localhost:35000/mission/nagar-slm-service:phase7d-1 deploy/phases/07-app-slm
#
# Hardened per SECURITY §5/§7: pinned base, non-root uid, read-only-root compatible,
# tests NOT shipped. The service holds NO database role of its own: DATABASE_URL is needed
# only for the sessions jti-denylist check (shared nagar-jwt chain).
FROM python:3.12-slim

COPY slm/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --requirement /app/requirements.txt \
    && adduser --disabled-password --uid 1000 --gecos "" nagar

COPY --chown=1000:1000 slm/app.py /app/

USER 1000
WORKDIR /app
ENV PYTHONUNBUFFERED=1
EXPOSE 4004
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "4004"]
