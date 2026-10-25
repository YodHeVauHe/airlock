"""Sandbox driver factory."""
from __future__ import annotations

from ..config import Settings
from .base import SandboxDriver
from .docker_driver import DockerDriver
from .local_driver import LocalDriver
from .vultr_driver import VultrInstanceDriver

_drivers: dict[str, SandboxDriver] = {}


def get_driver(settings: Settings) -> SandboxDriver:
    key = settings.driver
    if key not in _drivers:
        if key == "docker":
            _drivers[key] = DockerDriver(image=settings.sandbox_image, network=settings.docker_network)
        elif key == "vultr":
            if not (settings.vultr_driver_enabled and settings.vultr_api_key):
                raise RuntimeError(
                    "vultr driver needs VULTR_API_KEY and AIRLOCK_VULTR_DRIVER=1; "
                    "falling back would silently weaken containment — refusing"
                )
            import secrets as _secrets
            _drivers[key] = VultrInstanceDriver(
                api_key=settings.vultr_api_key,
                region=settings.vultr_region,
                plan=settings.vultr_plan,
                callback_secret=_secrets.token_hex(32),  # per-process; restart re-keys runs
                public_url=settings.public_url or "http://127.0.0.1:8000",
            )
        else:
            _drivers[key] = LocalDriver()
    return _drivers[key]


def driver_health(settings: Settings) -> dict:
    """Cheap, non-destructive readiness info for the status endpoint."""
    info = {"configured": settings.driver}
    if settings.driver == "docker":
        try:
            import subprocess
            r = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                               capture_output=True, text=True, timeout=10)
            info["docker_ok"] = r.returncode == 0
            info["docker_version"] = r.stdout.strip() if r.returncode == 0 else r.stderr.strip()[:120]
            img = subprocess.run(["docker", "image", "inspect", settings.sandbox_image],
                                 capture_output=True, timeout=10)
            info["sandbox_image_present"] = img.returncode == 0
        except Exception as exc:  # docker CLI missing
            info["docker_ok"] = False
            info["error"] = str(exc)[:200]
    elif settings.driver == "vultr":
        info["enabled"] = settings.vultr_driver_enabled and bool(settings.vultr_api_key)
    return info
