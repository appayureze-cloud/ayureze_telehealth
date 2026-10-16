FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Build-time-only HTTPS proxy/CA trust for sandboxes that route outbound
# HTTPS through a local TLS-intercepting proxy (see /root/.ccr/README.md in
# the Claude Code sandbox this was built in). The bracket glob makes the
# COPY optional: on a normal host with unrestricted network access, no
# ca-bundle.crt file is present, the glob matches nothing, and this whole
# block is a no-op. The HTTPS_PROXY build arg is scoped to the single `pip
# install` RUN below, not baked into the runtime image's environment.
ARG HTTPS_PROXY=
COPY ca-bundle.cr[t] /tmp/
RUN if [ -f /tmp/ca-bundle.crt ]; then \
        cp /tmp/ca-bundle.crt /usr/local/share/ca-certificates/build-proxy-ca.crt && \
        update-ca-certificates && \
        rm -f /tmp/ca-bundle.crt; \
    fi

WORKDIR /app

# The full source tree must be present before `pip install .` runs: this
# project's pyproject.toml lists its own local packages
# ([tool.setuptools] packages = [...]), so setuptools needs api/, models/,
# etc. on disk to build the wheel — copying only pyproject.toml first (as
# an earlier version of this Dockerfile did) fails with "package directory
# 'api' does not exist" on any machine, not just this one.
COPY . .
RUN HTTPS_PROXY="${HTTPS_PROXY}" PIP_CERT=/etc/ssl/certs/ca-certificates.crt \
    pip install --no-cache-dir .

EXPOSE 8100

CMD ["sh", "-c", "alembic upgrade head && uvicorn api.main:app --host 0.0.0.0 --port 8100"]
