# frontend image — Phase 7g (ADR-013 fresh rebuild).
#
# Build context is the PHASE DIRECTORY (established pattern; the host daemon cannot
# resolve the k3d registry alias — G0.3):
#   docker build -f deploy/phases/07-app-ui/frontend/Dockerfile \
#     -t localhost:35000/mission/nagar-frontend:phase7g-1 deploy/phases/07-app-ui
#
# Hardened per SECURITY §5/§7: pinned base, non-root uid, read-only-root compatible
# (standalone server writes nothing but its socket/tmp), tests NOT shipped.
FROM node:22-slim AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3001 HOSTNAME=0.0.0.0
COPY --from=build --chown=1000:1000 /app/.next/standalone ./
COPY --from=build --chown=1000:1000 /app/.next/static ./.next/static
COPY --from=build --chown=1000:1000 /app/public ./public
# node:22-slim ships the `node` user at uid/gid 1000.
USER 1000
EXPOSE 3001
CMD ["node", "server.js"]
