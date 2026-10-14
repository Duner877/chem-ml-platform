# Chem ML Platform v0.7.1 -- single stage image.
#
# Builds the FastAPI backend, bundles the pre-built React frontend and serves
# everything from one container:
#
#   docker build -t chem-ml-platform .
#   docker run --rm -p 8000:8000 chem-ml-platform
#
# The scientific nodes are pure Python + NumPy/SciPy, so no heavy system
# dependencies are required.  PyTorch is installed (CPU wheel) for the
# optional MPNN training backend.

FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# System packages needed by the scientific stack.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt


FROM python:3.11-slim

LABEL org.opencontainers.image.title="Chem ML Platform" \
      org.opencontainers.image.version="0.7.1" \
      org.opencontainers.image.description="Node-based scientific workflow platform" \
      org.opencontainers.image.licenses="Apache-2.0"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CHEMML_HOST=0.0.0.0 \
    CHEMML_PORT=8000 \
    PYTHONPATH=/app:/app/node_sdk/python \
    PATH=/home/chemml/.local/bin:$PATH

WORKDIR /app

# Runtime system libraries used by NumPy / SciPy / matplotlib.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user owning the application and the output directory.
RUN useradd --create-home --shell /usr/sbin/nologin chemml

COPY --from=builder /root/.local /home/chemml/.local

# Application code.
COPY backend/ ./backend/
COPY workflow_engine/ ./workflow_engine/
COPY data_layer/ ./data_layer/
COPY models/ ./models/
COPY simulations/ ./simulations/
COPY databases/ ./databases/
COPY nodes/ ./nodes/
COPY ai_runtime/ ./ai_runtime/
COPY database_runtime/ ./database_runtime/
COPY simulation_runtime/ ./simulation_runtime/
COPY report_agent/ ./report_agent/
COPY node_registry/ ./node_registry/
COPY datasets/ ./datasets/
COPY workflows/ ./workflows/
COPY node_sdk/ ./node_sdk/

# Pre-built frontend (produced by `npm run build` in frontend/).  When the
# directory is absent the API still runs and /api/docs stays available.
COPY frontend/dist/ ./static/

RUN mkdir -p /app/output /app/plugins && chown -R chemml:chemml /app

USER chemml

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status==200 else 1)"

CMD ["sh", "-c", "python -m uvicorn backend.app:app --host ${CHEMML_HOST:-0.0.0.0} --port ${CHEMML_PORT:-8000} --workers ${CHEMML_WORKERS:-2}"]
