# Control-plane image — Airlock itself, deployed on the Vultr VM.
# It needs the docker CLI to spawn SIBLING sandbox containers on the host
# daemon (docker-outside-of-docker). The daemon socket is mounted read-only
# by docker-compose.yml. Secrets come from env at run time, never baked in.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends docker.io ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/airlock
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

RUN useradd --uid 1000 airlock && mkdir -p /data && chown -R airlock:airlock /srv /data
USER airlock
ENV AIRLOCK_DATA_DIR=/data
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
