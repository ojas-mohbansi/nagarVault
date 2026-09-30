# vault-ui injector image — Phase 7g (ADR-013 fresh rebuild).
#
# Build context is the PHASE DIRECTORY:
#   docker build -f deploy/phases/07-app-ui/vault-ui/Dockerfile \
#     -t localhost:35000/mission/nagar-vault-ui:phase7g-1 deploy/phases/07-app-ui
#
# Dev overlay (CONVENTIONS §4: never edge-exposed). Plain node, zero runtime deps;
# tests NOT shipped.
FROM node:22-slim
WORKDIR /app
COPY vault-ui/server.js vault-ui/package.json ./
COPY vault-ui/src ./src
# node:22-slim ships the `node` user at uid/gid 1000.
USER 1000
ENV NODE_ENV=production
EXPOSE 5173
CMD ["node", "server.js"]
