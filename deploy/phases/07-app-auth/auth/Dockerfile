# authService image — Phase 7a (ADR-013 fresh rebuild).
#
# Build context is the PHASE DIRECTORY (established Phase-6 pattern; the host daemon
# cannot resolve the k3d registry alias, so the build uses the upstream base and the
# result is retagged/pushed to the internal registry — G0.3):
#   docker build -f deploy/phases/07-app-auth/auth/Dockerfile \
#     -t localhost:35000/mission/nagar-auth-service:phase7a-1 deploy/phases/07-app-auth
#
# Hardened per SECURITY §5/§7: pinned base, non-root uid, no shell tools needed at
# runtime, uvicorn as PID 1 via exec form. Tests are NOT copied into the image —
# they run on the host (hermetic suite) and the real E2E runs against the Deployment.
FROM python:3.12-slim

COPY auth/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --requirement /app/requirements.txt \
    && adduser --disabled-password --uid 1000 --gecos "" nagar

COPY --chown=1000:1000 auth/app.py auth/seed_admin.py /app/

USER 1000
WORKDIR /app
ENV PYTHONUNBUFFERED=1
EXPOSE 4000
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "4000"]
