"""Persistence layer.

Primary target is a local JSON store (`data/db.json`) so the server boots and
tests run with zero external services. PostgreSQL and Redis are *optional*
accelerants: when connection strings are provided the service probes them and
reports health, but never hard-fails when they are absent.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from . import settings

_LOCK = threading.RLock()
_DB_PATH = settings.DATA_DIR / "db.json"

_EMPTY: dict[str, Any] = {
    "users": {},
    "shots": {},
    "settings": {},
}


def _read() -> dict[str, Any]:
    if not _DB_PATH.exists():
        return json.loads(json.dumps(_EMPTY))
    try:
        data = json.loads(_DB_PATH.read_text(encoding="utf-8"))
    except Exception:
        return json.loads(json.dumps(_EMPTY))
    for key, default in _EMPTY.items():
        data.setdefault(key, json.loads(json.dumps(default)))
    return data


def _write(data: dict[str, Any]) -> None:
    settings.ensure_dirs()
    tmp = _DB_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_DB_PATH)


def read_store() -> dict[str, Any]:
    with _LOCK:
        return _read()


def write_store(data: dict[str, Any]) -> None:
    with _LOCK:
        _write(data)


# --- users ----------------------------------------------------------------

def get_user(username: str) -> dict[str, Any] | None:
    return read_store()["users"].get(username)


def put_user(username: str, record: dict[str, Any]) -> None:
    with _LOCK:
        data = _read()
        data["users"][username] = record
        _write(data)


def seed_admin(username: str, password: str) -> bool:
    """Create the fallback admin account if absent. Returns True if created."""
    from .auth import hash_password

    with _LOCK:
        data = _read()
        if username in data["users"]:
            return False
        data["users"][username] = {
            "username": username,
            "password_hash": hash_password(password),
            "role": "admin",
            "created_at": int(time.time()),
        }
        _write(data)
        return True


# --- shots ----------------------------------------------------------------

def list_shots() -> list[dict[str, Any]]:
    shots = list(read_store()["shots"].values())
    shots.sort(key=lambda s: s.get("created_at", 0), reverse=True)
    return shots


def put_shot(shot_id: str, record: dict[str, Any]) -> None:
    with _LOCK:
        data = _read()
        data["shots"][shot_id] = record
        _write(data)


def get_shot(shot_id: str) -> dict[str, Any] | None:
    return read_store()["shots"].get(shot_id)


def delete_shot(shot_id: str) -> bool:
    with _LOCK:
        data = _read()
        if shot_id not in data["shots"]:
            return False
        del data["shots"][shot_id]
        _write(data)
        return True


# --- health ---------------------------------------------------------------

LAST_ERROR: dict[str, str] = {}


def check_postgres() -> bool:
    url = settings.DATABASE_URL
    if not url:
        LAST_ERROR["postgres"] = "DATABASE_URL not configured"
        return False
    try:
        import psycopg  # type: ignore

        with psycopg.connect(url, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        LAST_ERROR.pop("postgres", None)
        return True
    except Exception as exc:
        LAST_ERROR["postgres"] = str(exc).strip().splitlines()[0][:200]
        return False


def check_redis() -> bool:
    url = settings.REDIS_URL
    if not url:
        LAST_ERROR["redis"] = "REDIS_URL not configured"
        return False
    try:
        import redis  # type: ignore

        client = redis.from_url(url, socket_connect_timeout=3)
        ok = bool(client.ping())
        if ok:
            LAST_ERROR.pop("redis", None)
        else:
            LAST_ERROR["redis"] = "ping returned falsy"
        return ok
    except Exception as exc:
        LAST_ERROR["redis"] = str(exc).strip().splitlines()[0][:200]
        return False


def shot_file_path(shot_id: str) -> Path:
    return settings.SHOTS_DIR / f"{shot_id}.png"