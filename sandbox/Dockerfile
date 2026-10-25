# Airlock sandbox image — the disposable environment agent code runs in.
# Built on the Vultr VM by deploy/setup-vm.sh as airlock-sandbox:latest.
#
# Containment properties (enforced by the driver's docker flags at run time):
#   - runs as unprivileged uid 1000 (never root)
#   - read-only rootfs at run time; only /workspace (per-task bind) is writable
#   - no network (--network none), no capabilities (--cap-drop ALL)
#   - this image contains NO secrets and NO control-plane code
FROM python:3.12-slim

# data-science essentials for Pattern A lanes; keep the image lean
RUN pip install --no-cache-dir pandas matplotlib \
    && useradd --uid 1000 --create-home sandbox

# playwright lane (Pattern B) is layered separately: see Dockerfile.browser
RUN mkdir -p /workspace && chown sandbox:sandbox /workspace
USER sandbox
WORKDIR /workspace
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
