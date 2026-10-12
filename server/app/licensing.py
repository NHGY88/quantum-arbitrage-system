"""Phase 7 - Licensing / Keygen-style authorization.

Self-contained so the product works without a third-party account. The API
shape deliberately mirrors Keygen.sh (machine fingerprints, activate /
validate / deallocate) so a real Keygen backend can be swapped in later by
changing `PROVIDER`.

Storage: PostgreSQL when reachable, JSON fallback otherwise.
"""

from __future__ import annotations

import hashlib
import platform
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from . import db, settings

PROVIDER = settings.get("LICENSE_PROVIDER", "local")

_STATUS_ACTIVE = "active"
_STATUS_SUSPENDED = "suspended"
_STATUS_EXPIRED = "expired"


# --- key format -----------------------------------------------------------

PREFIX = "QE"


def _b32(data: bytes) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # Crockford-ish, no I/O/0/1
    num = int.from_bytes(data, "big")
    out = []
    for _ in range(len(data) * 8 // 5):
        out.append(alphabet[num & 31])
        num >>= 5
    return "".join(reversed(out))


def generate_license_key() -> str:
    """Human-friendly key: QE-XXXXX-XXXXX-XXXXX-XXXXX."""
    raw = secrets.token_bytes(20)
    body = _b32(raw)
    groups = [body[i : i + 5] for i in range(0, 20, 5)]
    return f"{PREFIX}-" + "-".join(groups)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.strip().upper().encode("utf-8")).hexdigest()


def fingerprint() -> str:
    """Stable-ish machine fingerprint for seat binding."""
    parts = [
        platform.node() or "",
        platform.machine() or "",
        platform.processor() or "",
        str(uuid.getnode()),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


# --- persistence (PostgreSQL preferred) ----------------------------------

_PG_OK: bool | None = None


def _conn():
    import psycopg  # type: ignore

    return psycopg.connect(settings.DATABASE_URL, connect_timeout=3)


def _pg_ready() -> bool:
    global _PG_OK
    if _PG_OK is None:
        _PG_OK = db.check_postgres()
    return bool(_PG_OK)


def _ensure_table() -> None:
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS licenses (
                id           TEXT PRIMARY KEY,
                key_hash     TEXT UNIQUE NOT NULL,
                key_prefix   TEXT NOT NULL,
                label        TEXT NOT NULL DEFAULT '',
                plan         TEXT NOT NULL DEFAULT 'pro',
                status       TEXT NOT NULL DEFAULT 'active',
                max_machines INTEGER NOT NULL DEFAULT 1,
                expires_at   TIMESTAMPTZ,
                notes        TEXT NOT NULL DEFAULT '',
                created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS license_activations (
                id           TEXT PRIMARY KEY,
                license_id   TEXT NOT NULL REFERENCES licenses(id) ON DELETE CASCADE,
                fingerprint  TEXT NOT NULL,
                activated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                last_seen    TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (license_id, fingerprint)
            )
            """
        )


def _row_to_license(row: tuple) -> dict[str, Any]:
    return {
        "id": row[0],
        "key_prefix": row[1],
        "label": row[2],
        "plan": row[3],
        "status": row[4],
        "max_machines": row[5],
        "expires_at": row[6].isoformat() if row[6] else None,
        "notes": row[7],
        "created_at": row[8].isoformat() if row[8] else None,
    }


def list_licenses() -> list[dict[str, Any]]:
    if _pg_ready():
        try:
            _ensure_table()
            with _conn() as c, c.cursor() as cur:
                cur.execute(
                    "SELECT id,key_prefix,label,plan,status,max_machines,"
                    "expires_at,notes,created_at FROM licenses ORDER BY created_at DESC"
                )
                return [_row_to_license(r) for r in cur.fetchall()]
        except Exception:
            pass
    return list(db.read_store().get("licenses", {}).values())


def create_license(
    *,
    label: str = "",
    plan: str = "pro",
    max_machines: int = 1,
    days: int | None = 365,
    notes: str = "",
) -> dict[str, Any]:
    key = generate_license_key()
    lid = uuid.uuid4().hex
    expires = datetime.now(timezone.utc) + timedelta(days=days) if days else None
    prefix = key[:9] + "…"

    if _pg_ready():
        try:
            _ensure_table()
            with _conn() as c, c.cursor() as cur:
                cur.execute(
                    "INSERT INTO licenses (id,key_hash,key_prefix,label,plan,status,"
                    "max_machines,expires_at,notes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (lid, hash_key(key), prefix, label, plan, _STATUS_ACTIVE,
                     max_machines, expires, notes),
                )
            return {"id": lid, "key": key, "key_prefix": prefix, "label": label,
                    "plan": plan, "max_machines": max_machines,
                    "expires_at": expires.isoformat() if expires else None}
        except Exception:
            pass

    with db._LOCK:
        data = db._read()
        data.setdefault("licenses", {})
        data["licenses"][lid] = {
            "id": lid, "key": key, "key_hash": hash_key(key), "key_prefix": prefix,
            "label": label, "plan": plan, "status": _STATUS_ACTIVE,
            "max_machines": max_machines,
            "expires_at": expires.isoformat() if expires else None,
            "notes": notes, "created_at": int(time.time()),
        }
        db._write(data)
    return {"id": lid, "key": key, "key_prefix": prefix, "label": label,
            "plan": plan, "max_machines": max_machines,
            "expires_at": expires.isoformat() if expires else None}


def _find_by_hash(kh: str) -> dict[str, Any] | None:
    if _pg_ready():
        try:
            _ensure_table()
            with _conn() as c, c.cursor() as cur:
                cur.execute(
                    "SELECT id,key_hash,key_prefix,label,plan,status,max_machines,"
                    "expires_at,notes,created_at FROM licenses WHERE key_hash=%s",
                    (kh,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "id": row[0], "key_hash": row[1], "key_prefix": row[2],
                    "label": row[3], "plan": row[4], "status": row[5],
                    "max_machines": row[6],
                    "expires_at": row[6] if False else (row[7].isoformat() if row[7] else None),
                    "notes": row[8],
                    "created_at": row[9].isoformat() if row[9] else None,
                }
        except Exception:
            pass
    for lic in db.read_store().get("licenses", {}).values():
        if lic.get("key_hash") == kh:
            return lic
    return None


def _expired(expires_at: Any) -> bool:
    if not expires_at:
        return False
    if isinstance(expires_at, str):
        try:
            expires_at = datetime.fromisoformat(expires_at)
        except ValueError:
            return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at < datetime.now(timezone.utc)


def activate(key: str, fp: str, meta: dict | None = None) -> dict[str, Any]:
    kh = hash_key(key)
    lic = _find_by_hash(kh)
    if not lic:
        return {"valid": False, "code": "not_found",
                "message": "授权码不存在"}
    if lic.get("status") == _STATUS_SUSPENDED:
        return {"valid": False, "code": "suspended", "message": "授权码已被停用"}
    if _expired(lic.get("expires_at")):
        return {"valid": False, "code": "expired", "message": "授权码已过期"}

    lid = lic["id"]

    if _pg_ready():
        try:
            with _conn() as c, c.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM license_activations WHERE license_id=%s",
                    (lid,),
                )
                used = cur.fetchone()[0]
                cur.execute(
                    "SELECT 1 FROM license_activations WHERE license_id=%s AND fingerprint=%s",
                    (lid, fp),
                )
                already = cur.fetchone() is not None
                if already:
                    cur.execute(
                        "UPDATE license_activations SET last_seen=now() "
                        "WHERE license_id=%s AND fingerprint=%s",
                        (lid, fp),
                    )
                elif used < int(lic.get("max_machines", 1)):
                    cur.execute(
                        "INSERT INTO license_activations (id,license_id,fingerprint) "
                        "VALUES (%s,%s,%s)",
                        (uuid.uuid4().hex, lid, fp),
                    )
                else:
                    return {"valid": False, "code": "seat_limit",
                            "message": "授权设备数已达上限"}
            return {"valid": True, "code": "ok", "license": {
                "id": lid, "label": lic.get("label", ""),
                "plan": lic.get("plan", "pro"),
                "max_machines": lic.get("max_machines", 1),
                "expires_at": lic.get("expires_at"),
            }, "machine": fp}
        except Exception:
            pass

    acts = db.read_store().setdefault("activations", {}).setdefault(lid, {})
    if fp not in acts and len(acts) >= int(lic.get("max_machines", 1)):
        return {"valid": False, "code": "seat_limit", "message": "授权设备数已达上限"}
    acts[fp] = {"last_seen": int(time.time()), **(meta or {})}
    data = db.read_store()
    data["activations"][lid] = acts
    db.write_store(data)
    return {"valid": True, "code": "ok", "license": {
        "id": lid, "label": lic.get("label", ""), "plan": lic.get("plan", "pro"),
        "max_machines": lic.get("max_machines", 1),
        "expires_at": lic.get("expires_at"),
    }, "machine": fp}


def validate(key: str, fp: str) -> dict[str, Any]:
    return activate(key, fp)


def revoke(license_id: str) -> bool:
    if _pg_ready():
        try:
            with _conn() as c, c.cursor() as cur:
                cur.execute("DELETE FROM licenses WHERE id=%s", (license_id,))
                return cur.rowcount > 0
        except Exception:
            pass
    data = db.read_store()
    if license_id in data.get("licenses", {}):
        del data["licenses"][license_id]
        data.get("activations", {}).pop(license_id, None)
        db.write_store(data)
        return True
    return False


def set_status(license_id: str, status: str) -> bool:
    if status not in (_STATUS_ACTIVE, _STATUS_SUSPENDED):
        raise ValueError("invalid status")
    if _pg_ready():
        try:
            with _conn() as c, c.cursor() as cur:
                cur.execute("UPDATE licenses SET status=%s WHERE id=%s",
                            (status, license_id))
                return cur.rowcount > 0
        except Exception:
            pass
    data = db.read_store()
    lic = data.get("licenses", {}).get(license_id)
    if not lic:
        return False
    lic["status"] = status
    db.write_store(data)
    return True
