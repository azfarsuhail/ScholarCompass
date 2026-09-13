# 512MB hard ceiling drives every choice in this file.
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# tesseract-ocr + the English traineddata. ~45MB total.
# This is the entire OCR stack: no torch, no CUDA, no model download at runtime.
# eng is the only language pack installed because transcripts we handle are
# either English or use Western numerals for the grades we actually parse.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt

COPY app ./app

# Run as non-root. Uploads are processed in memory, so there is no writable
# data directory to own.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

# ONE worker on purpose.
#   * Each uvicorn worker is a full Python process (~90MB RSS with these deps).
#     Two workers plus a Tesseract subprocess (~60MB peak per page) will OOM in
#     512MB. Scale by running more containers, not more workers per container.
#   * The workload is IO-bound (Neon, Groq, Orizn), so async concurrency inside
#     one worker is what actually buys throughput here.
#
# Shell form so $PORT expands. Hosts that assign a port (Render and most
# container PaaS) inject it as $PORT and route only to that port -- and the
# exec form this replaced would have passed the literal string "$PORT" to
# uvicorn, or silently kept listening on 8000 while the platform sent traffic
# somewhere else. That failure looks like a healthy container serving nothing.
# The default keeps `docker run -p 8000:8000` and docker-compose working.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
