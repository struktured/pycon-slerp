FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app
COPY static ./static

# Where SQLite + the SerpApi response cache live — mounted as a Fly volume
# in production so the cache survives deploys.
ENV PYCON_DATA_DIR=/data
RUN mkdir -p /data

EXPOSE 8080

# Granian is the Rust-powered ASGI server (credit: enterprise-Python / async-IO
# spirit of the conference). Falls back to uvicorn if not installed.
CMD ["granian", "--interface", "asgi", "--host", "0.0.0.0", "--port", "8080", "app.main:app"]
