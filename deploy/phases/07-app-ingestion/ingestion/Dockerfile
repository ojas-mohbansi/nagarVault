# ingestion backend image — Phase 7e (ADR-013 fresh rebuild).
#
# Build context is the PHASE DIRECTORY (established pattern; G0.3 daemon alias limitation):
#   docker build -f deploy/phases/07-app-ingestion/ingestion/Dockerfile \
#     -t localhost:35000/mission/nagar-ingestion:phase7e-1 deploy/phases/07-app-ingestion
#
# Hardened per SECURITY §5/§7: pinned base (Node 22 slim), non-root uid, read-only-root
# compatible, tests NOT shipped. node_modules ships (built on the host during CI/build).
FROM node:22-slim

COPY ingestion/package.json ingestion/package-lock.json /app/
# node:22-slim ships the `node` user at uid/gid 1000 — no user creation needed.
RUN cd /app && npm ci --omit=dev

COPY --chown=1000:1000 ingestion/src /app/src

USER 1000
WORKDIR /app
ENV NODE_ENV=production
EXPOSE 3000
CMD ["node", "src/runtime.js"]
