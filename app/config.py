"""Central configuration. Everything comes from env with sane defaults.

Secrets (inference API key) live ONLY in the control-plane process. They are
never passed into a sandbox — that invariant is enforced by the sandbox
drivers, which build the environment for the sandbox from scratch.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    # --- runtime ---
    host: str = os.environ.get("AIRLOCK_HOST", "0.0.0.0")
    port: int = int(os.environ.get("AIRLOCK_PORT", "8000"))
    data_dir: Path = Path(os.environ.get("AIRLOCK_DATA_DIR", "./data")).resolve()
    public_url: str = os.environ.get("AIRLOCK_PUBLIC_URL", "").rstrip("/")

    # --- sandbox driver: "local" (dev), "docker" (production on the Vultr VM) ---
    driver: str = os.environ.get("AIRLOCK_DRIVER", "local")

    # --- sandbox resource caps (enforced by the driver, not the agent) ---
    timeout_s: int = int(os.environ.get("AIRLOCK_TIMEOUT_S", "60"))
    mem_mb: int = int(os.environ.get("AIRLOCK_MEM_MB", "512"))
    cpus: float = float(os.environ.get("AIRLOCK_CPUS", "1.0"))
    pids: int = int(os.environ.get("AIRLOCK_PIDS", "128"))
    max_output_bytes: int = int(os.environ.get("AIRLOCK_MAX_OUTPUT_BYTES", str(256 * 1024)))
    max_artifact_bytes: int = int(os.environ.get("AIRLOCK_MAX_ARTIFACT_BYTES", str(20 * 1024 * 1024)))

    # --- sandbox image (docker driver) ---
    sandbox_image: str = os.environ.get("AIRLOCK_SANDBOX_IMAGE", "airlock-sandbox:latest")
    docker_network: str = os.environ.get("AIRLOCK_DOCKER_NETWORK", "none")

    # --- policy: "enforce" blocks hard-violations before execution, "monitor" only records ---
    policy_mode: str = os.environ.get("AIRLOCK_POLICY_MODE", "enforce")

    # --- Vultr Serverless Inference (OpenAI-compatible) ---
    inference_base_url: str = os.environ.get(
        "AIRLOCK_INFERENCE_BASE_URL", "https://api.vultrinference.com/v1"
    ).rstrip("/")
    inference_api_key: str = os.environ.get("AIRLOCK_INFERENCE_API_KEY", "")
    inference_model: str = os.environ.get("AIRLOCK_INFERENCE_MODEL", "")
    mock_llm: bool = field(default_factory=lambda: _bool("AIRLOCK_MOCK_LLM", False))

    # --- agent loop ---
    max_revisions: int = int(os.environ.get("AIRLOCK_MAX_REVISIONS", "3"))

    # --- vultr throwaway-instance driver (experimental; needs Vultr API key) ---
    vultr_api_key: str = os.environ.get("VULTR_API_KEY", "")
    vultr_region: str = os.environ.get("AIRLOCK_VULTR_REGION", "ewr")
    vultr_plan: str = os.environ.get("AIRLOCK_VULTR_PLAN", "vc2-1-1")
    vultr_driver_enabled: bool = field(default_factory=lambda: _bool("AIRLOCK_VULTR_DRIVER", False))

    def ensure_dirs(self) -> None:
        (self.data_dir / "workspaces").mkdir(parents=True, exist_ok=True)

    @property
    def llm_is_mock(self) -> bool:
        return self.mock_llm or not self.inference_api_key


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.ensure_dirs()
    return _settings


def reset_settings_for_tests() -> Settings:
    global _settings
    _settings = Settings()
    _settings.ensure_dirs()
    return _settings
