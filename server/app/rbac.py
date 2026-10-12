"""Role-based access control.

The super-admin (role=`admin`) creates every account and grants permissions.
Permissions are grouped into five business categories, each with granular
actions:

  combo   组合 / 组合交易   - build & manage hedge combinations
  trade   交易             - orders and risk execution
  me      我的             - personal data & settings
  notice  公告             - announcements
  backend 后台任务          - system / operations jobs

Design notes:
  * super-admin implicitly holds every permission (no per-action bookkeeping)
  * a user's effective permission set = union(role perms, direct grants)
  * grants can be allowed (+) or explicitly denied (-); deny always wins
  * everything persists in PostgreSQL when available, JSON otherwise
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Iterable

from . import db, settings

ROLE_ADMIN = "admin"
ROLE_USER = "user"

# --- permission catalogue -------------------------------------------------

PERMISSIONS: dict[str, dict[str, str]] = {
    "combo": {
        "combo:read": "查看组合",
        "combo:write": "创建/编辑组合",
        "combo:delete": "删除组合",
        "combo:trade": "执行组合交易",
    },
    "trade": {
        "trade:read": "查看交易",
        "trade:order": "下单",
        "trade:risk": "调整风控",
        "trade:execute": "执行交易",
    },
    "me": {
        "me:read": "查看个人数据",
        "me:write": "修改个人资料",
        "me:settings": "个人设置",
    },
    "notice": {
        "notice:read": "查看公告",
        "notice:write": "发布公告",
        "notice:manage": "管理公告",
    },
    "backend": {
        "backend:read": "查看后台状态",
        "backend:jobs": "运行后台任务",
        "backend:manage": "管理系统",
        "backend:users": "管理用户与权限",
    },
}

CATEGORY_LABELS: dict[str, str] = {
    "combo": "组合 / 组合交易",
    "trade": "交易",
    "me": "我的",
    "notice": "公告",
    "backend": "后台任务",
}

ALL_PERMISSIONS: list[str] = [p for group in PERMISSIONS.values() for p in group]

ROLE_PRESETS: dict[str, list[str]] = {
    "viewer": ["combo:read", "trade:read", "me:read", "me:write", "me:settings", "notice:read"],
    "trader": [
        "combo:read", "combo:write", "combo:trade",
        "trade:read", "trade:order", "trade:execute",
        "me:read", "me:write", "me:settings", "notice:read",
    ],
    "operator": [
        "combo:read", "combo:write", "combo:delete", "combo:trade",
        "trade:read", "trade:order", "trade:risk", "trade:execute",
        "me:read", "me:write", "me:settings",
        "notice:read", "notice:write",
        "backend:read", "backend:jobs",
    ],
}

ROLE_LABELS: dict[str, str] = {
    "admin": "最高权限管理员",
    "user": "普通用户",
    "viewer": "只读",
    "trader": "交易员",
    "operator": "运维",
}


def is_super(role: str) -> bool:
    return role == ROLE_ADMIN


def preset_permissions(role: str) -> list[str]:
    return list(ROLE_PRESETS.get(role, []))


# --- persistence ----------------------------------------------------------

_PG_TRIED = False


def _conn():
    import psycopg  # type: ignore

    return psycopg.connect(settings.DATABASE_URL, connect_timeout=3)


def _pg() -> bool:
    global _PG_TRIED
    if not _PG_TRIED:
        _PG_TRIED = db.check_postgres()
    return _PG_TRIED


def ensure_schema() -> None:
    if not _pg():
        return
    try:
        with _conn() as c, c.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS app_users (
                    username      TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    role          TEXT NOT NULL DEFAULT 'user',
                    display_name  TEXT NOT NULL DEFAULT '',
                    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_permissions (
                    username   TEXT NOT NULL,
                    permission TEXT NOT NULL,
                    effect     TEXT NOT NULL DEFAULT 'allow',
                    PRIMARY KEY (username, permission)
                )
                """
            )
    except Exception:
        pass


def _store() -> dict[str, Any]:
    data = db.read_store()
    data.setdefault("users", {})
    data.setdefault("permissions", {})
    return data


def save_store(data: dict[str, Any]) -> None:
    db.write_store(data)


# --- users ----------------------------------------------------------------

def create_user(
    username: str,
    password: str,
    *,
    role: str = ROLE_USER,
    display_name: str = "",
    permissions: Iterable[str] | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    from .auth import hash_password

    username = username.strip()
    if not username:
        raise ValueError("username required")

    if _pg():
        try:
            ensure_schema()
            with _conn() as c, c.cursor() as cur:
                cur.execute(
                    "INSERT INTO app_users (username,password_hash,role,display_name,enabled)"
                    " VALUES (%s,%s,%s,%s,%s) ON CONFLICT (username) DO UPDATE SET"
                    " password_hash=EXCLUDED.password_hash, role=EXCLUDED.role,"
                    " display_name=EXCLUDED.display_name, enabled=EXCLUDED.enabled",
                    (username, hash_password(password), role, display_name, enabled),
                )
            set_permissions(username, permissions if permissions is not None else preset_permissions(role))
            return get_user(username) or {}
        except Exception:
            pass

    data = _store()
    prev = data["users"].get(username, {})
    data["users"][username] = {
        "username": username,
        "password_hash": hash_password(password),
        "role": role,
        "display_name": display_name or prev.get("display_name", ""),
        "enabled": enabled,
        "created_at": prev.get("created_at", int(time.time())),
    }
    save_store(data)
    set_permissions(
        username,
        permissions if permissions is not None else prev.get("permissions", preset_permissions(role)),
    )
    return get_user(username) or {}


def set_display_name(username: str, display_name: str) -> bool:
    """Self-service profile edit; only touches this user's own row."""
    if _pg():
        try:
            with _conn() as c, c.cursor() as cur:
                cur.execute(
                    "UPDATE app_users SET display_name=%s WHERE username=%s",
                    (display_name, username),
                )
                return cur.rowcount > 0
        except Exception:
            pass
    data = _store()
    rec = data["users"].get(username)
    if not rec:
        return False
    rec["display_name"] = display_name
    save_store(data)
    return True


def get_user(username: str) -> dict[str, Any] | None:
    if _pg():
        try:
            ensure_schema()
            with _conn() as c, c.cursor() as cur:
                cur.execute(
                    "SELECT username,role,display_name,enabled,created_at FROM app_users"
                    " WHERE username=%s",
                    (username,),
                )
                row = cur.fetchone()
            if not row:
                return None
            perms = get_permissions(row[0])
            return {
                "username": row[0],
                "role": row[1],
                "display_name": row[2],
                "enabled": bool(row[3]),
                "created_at": row[4].isoformat() if row[4] else None,
                "permissions": perms,
                "effective": effective_permissions(row[1], perms),
                "pending": not is_super(row[1]) and not effective_permissions(row[1], perms),
            }
        except Exception:
            pass

    data = _store()
    u = data["users"].get(username)
    if not u:
        return None
    perms = get_permissions(username)
    role = u.get("role", ROLE_USER)
    eff = effective_permissions(role, perms)
    return {
        "username": u["username"],
        "role": role,
        "display_name": u.get("display_name", ""),
        "enabled": u.get("enabled", True),
        "created_at": u.get("created_at"),
        "permissions": perms,
        "effective": eff,
        "pending": not is_super(role) and not eff,
    }


def list_users() -> list[dict[str, Any]]:
    names: list[str] = []
    if _pg():
        try:
            ensure_schema()
            with _conn() as c, c.cursor() as cur:
                cur.execute("SELECT username FROM app_users ORDER BY created_at")
                names = [r[0] for r in cur.fetchall()]
        except Exception:
            names = []
    if not names:
        names = list(_store()["users"].keys())
    out = []
    for n in names:
        u = get_user(n)
        if u:
            out.append(u)
    return out


def verify_user_password(username: str, password: str) -> dict[str, Any] | None:
    """Authenticate a user regardless of which store holds the record."""
    stored: str | None = None
    role = ROLE_USER
    enabled = True
    display_name = ""

    if _pg():
        try:
            ensure_schema()
            with _conn() as c, c.cursor() as cur:
                cur.execute(
                    "SELECT password_hash,role,display_name,enabled FROM app_users"
                    " WHERE username=%s",
                    (username,),
                )
                row = cur.fetchone()
            if row:
                stored, role, display_name, enabled = row[0], row[1], row[2], bool(row[3])
        except Exception:
            stored = None

    if stored is None:
        u = _store()["users"].get(username)
        if u:
            stored = u.get("password_hash")
            role = u.get("role", ROLE_USER)
            enabled = u.get("enabled", True)
            display_name = u.get("display_name", "")

    if not stored or not enabled:
        return None

    from .auth import verify_password

    if not verify_password(password, stored):
        return None
    return {"username": username, "role": role, "display_name": display_name}


# --- permissions ----------------------------------------------------------

def get_permissions(username: str) -> dict[str, str]:
    """Return {permission: 'allow'|'deny'} explicitly granted to the user."""
    out: dict[str, str] = {}
    if _pg():
        try:
            ensure_schema()
            with _conn() as c, c.cursor() as cur:
                cur.execute(
                    "SELECT permission,effect FROM user_permissions WHERE username=%s",
                    (username,),
                )
                out = {r[0]: r[1] for r in cur.fetchall()}
        except Exception:
            out = {}
    if not out:
        raw = _store()["permissions"].get(username)
        if isinstance(raw, dict):
            out = {k: v for k, v in raw.items() if v in ("allow", "deny")}
        elif isinstance(raw, list):
            out = {p: "allow" for p in raw}
    return out


def set_permissions(username: str, permissions: Iterable[str] | dict) -> dict[str, str]:
    if isinstance(permissions, dict):
        mapping = {k: v for k, v in permissions.items() if v in ("allow", "deny")}
    else:
        mapping = {p: "allow" for p in permissions}

    if _pg():
        try:
            ensure_schema()
            with _conn() as c, c.cursor() as cur:
                cur.execute("DELETE FROM user_permissions WHERE username=%s", (username,))
                for perm, eff in mapping.items():
                    cur.execute(
                        "INSERT INTO user_permissions (username,permission,effect)"
                        " VALUES (%s,%s,%s) ON CONFLICT (username,permission)"
                        " DO UPDATE SET effect=EXCLUDED.effect",
                        (username, perm, eff),
                    )
            return mapping
        except Exception:
            pass

    data = _store()
    data["permissions"][username] = mapping
    save_store(data)
    return mapping


def effective_permissions(role: str, explicit: dict[str, str] | None = None) -> list[str]:
    if is_super(role):
        return sorted(ALL_PERMISSIONS)
    explicit = explicit or {}
    granted = set(preset_permissions(role))
    for perm, eff in explicit.items():
        if eff == "deny":
            granted.discard(perm)
        else:
            granted.add(perm)
    return sorted(granted)


def has_permission(role: str, explicit: dict[str, str] | None, permission: str) -> bool:
    if is_super(role):
        return True
    return permission in effective_permissions(role, explicit)


def require_permission(user: dict, permission: str) -> None:
    if is_super(user.get("role", "")):
        return
    granted = effective_permissions(user.get("role", ROLE_USER),
                                   get_permissions(user["username"]))
    if permission not in granted:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail=f"缺少权限: {permission}")


def catalog() -> dict[str, Any]:
    return {
        "categories": [
            {
                "key": key,
                "label": CATEGORY_LABELS[key],
                "permissions": [
                    {"key": p, "label": label, "category": key}
                    for p, label in group.items()
                ],
            }
            for key, group in PERMISSIONS.items()
        ],
        "roles": [
            {"key": k, "label": ROLE_LABELS.get(k, k), "permissions": v}
            for k, v in ROLE_PRESETS.items()
        ],
        "admin_role": {"key": ROLE_ADMIN, "label": ROLE_LABELS[ROLE_ADMIN]},
    }
