"""Runtime settings loaded from an isolated admin.env file.

Configuration is deliberately kept out of source control: `admin.env` is
listed in `.gitignore` and is the ONLY place secrets are read from.
Environment variables always win over admin.env so that container
orchestration (docker-compose, Cloudflare Tunnel hosts, CI) can override
without editing files on disk.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / "admin.env"


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip()
        # strip matching single/double quotes
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        values[key.strip()] = val
    return values


_FILE_VALUES = _load_env_file(ENV_FILE)


def get(name: str, default: str = "") -> str:
    """Resolve a setting: process env wins, then admin.env, then default."""
    if name in os.environ:
        return os.environ[name]
    return _FILE_VALUES.get(name, default)


def get_int(name: str, default: int) -> int:
    raw = get(name, "")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def get_bool(name: str, default: bool = False) -> bool:
    raw = get(name, "")
    if not raw:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# --- core config -----------------------------------------------------------

# QE_DATA_DIR lets the test suite relocate all runtime state to a temp dir.
DATA_DIR = Path(get("QE_DATA_DIR", "") or (BASE_DIR / "data"))
SHOTS_DIR = DATA_DIR / "shots"
COMBOS_DIR = BASE_DIR / "combos"

APP_NAME = get("ADMIN_APP_NAME", "quantum-admin")
HOST = get("ADMIN_HOST", "0.0.0.0")
PORT = get_int("ADMIN_PORT", 8000)

JWT_SECRET = get("ADMIN_JWT_SECRET", "dev-only-change-me")
JWT_ALGO = "HS256"
TOKEN_TTL_SECONDS = get_int("ADMIN_TOKEN_TTL", 60 * 60 * 12)

SEED_USERNAME = get("ADMIN_SEED_USERNAME", "admin")
SEED_PASSWORD = get("ADMIN_SEED_PASSWORD", "ChangeMe123!")

# Optional datastores. Absent/invalid -> JSON fallback so the service still
# boots on a bare machine (this is the documented offline fallback).
DATABASE_URL = get("DATABASE_URL", "")
REDIS_URL = get("REDIS_URL", "")

# Hard risk controls from the blueprint.
MAX_MARGIN_RISK = float(get("MAX_MARGIN_RISK", "0.01"))  # 1% equity cap
MIN_LOT = float(get("MIN_LOT", "0.01"))

CORS_ORIGINS = [
    o.strip() for o in get("ADMIN_CORS_ORIGINS", "*").split(",") if o.strip()
]


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)