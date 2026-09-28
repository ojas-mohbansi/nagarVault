# git-repo-mirror — the cluster-reachable git transport for the disposable local
# substrate (ADR-014). Equivalent of the production internal git remote: the bare repo
# payload is staged into the image exactly like air-gapped images are staged into the
# internal registry. Rebuild + retag after each commit batch that Argo must consume:
#   git clone --bare <repo> payload/nagarvault.git   (at the desired commit)
#   docker build -t k3d-nagar.localhost:5000/mission/git-repo-mirror:<tag> .
#   docker push ...
# Read-only service (no receive-pack): Argo consumes; the OPERATOR pushes from the host
# by rebuilding the image — mirroring the registry staging model (OPERATIONS §2.3).
FROM alpine:3.20
# git-daemon is a separate alpine package (the base `git` package lacks the daemon
# subcommand); both are installed pinned by the apko-style apk index of the build host.
RUN apk add --no-cache git git-daemon && adduser -D -u 1000 gituser
COPY --chown=1000:1000 payload/nagarvault.git /srv/git/nagarvault.git
# COPY --chown normalizes file modes but not the tree write-bits git upload-pack needs;
# running as uid 1000 (PSS restricted) requires a readable+writable-by-owner object store.
RUN chmod -R u+rwX /srv/git/nagarvault.git
USER 1000
EXPOSE 9418
CMD ["git", "daemon", "--base-path=/srv/git", "--export-all", "--reuseaddr", "--port=9418", "--listen=0.0.0.0"]
