# Two dependency layers, matching requirements.txt / requirements-pipeline.txt:
# the base image always installs the small Day-5 lifecycle deps; the Day-6
# translation-pipeline deps (torch, transformers, faster-whisper, ...) are
# opt-in via the PIPELINE build arg so a lifecycle-only deployment (Mode A,
# AI absent) never pays for ~2GB of ML packages it will never load.
FROM python:3.11-slim-bookworm AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 ayureze && useradd --uid 10001 --gid ayureze --no-create-home --shell /usr/sbin/nologin ayureze

WORKDIR /app
COPY requirements.txt requirements-pipeline.txt ./

ARG PIPELINE=true
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$PIPELINE" = "true" ]; then \
         pip install --no-cache-dir -r requirements-pipeline.txt \
           --index-url https://download.pytorch.org/whl/cpu \
           --extra-index-url https://pypi.org/simple ; \
       fi

COPY app ./app

# models/ is intentionally NOT copied into the image — it is gitignored and
# ~2.5GB (see scripts/download_models.sh). Mount it as a volume at
# /app/models in production; AI_AGENT_ENABLE_PIPELINE=false (the default)
# never touches it, so a lifecycle-only deployment needs no volume at all.
RUN mkdir -p /app/models && chown -R ayureze:ayureze /app

USER ayureze:ayureze

EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8090/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
