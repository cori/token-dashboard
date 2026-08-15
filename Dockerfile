FROM python:3.12-slim

# curl is needed for HEALTHCHECK
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Run as root inside the container. The bind-mounted /data is owned
# by the host user; running as non-root requires careful permission
# gymnastics on every host. Root is fine for a single-tenant Runtipi
# app — the network exposure is via Traefik, not direct internet.
# (If you change this, also `chown -R 1000:1000 /data` from the
# compose file's healthcheck.)

# Install the package. The dashboard package has no third-party
# dependencies beyond stdlib + PyYAML (used by the legacy code).
WORKDIR /app
COPY --chown=root:root pyproject.toml /app/
COPY --chown=root:root dashboard /app/dashboard
RUN pip install --no-cache-dir /app/

# Where the dashboard reads/writes data. The Runtipi compose file
# bind-mounts this from the host.
ENV DATA_DIR=/data
ENV PORT=8000
ENV REFRESH_INTERVAL=300

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

CMD ["python", "-m", "dashboard.server"]