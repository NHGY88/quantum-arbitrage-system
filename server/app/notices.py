"""公告（Notice）模块。

对应权限分类 `notice`：
    notice:read    查看公告
    notice:write   发布公告
    notice:manage  编辑 / 删除 / 置顶公告

存储优先 PostgreSQL，表不存在时自动创建；不可用时回落 JSON。
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from . import db, settings

_pg_ok: bool | None = None


def _conn():
    import psycopg  # type: ignore

    return psycopg.connect(settings.DATABASE_URL, connect_timeout=3)


def _pg() -> bool:
    global _pg_ok
    if _pg_ok is None:
        _pg_ok = db.check_postgres()
    return bool(_pg_ok)


def ensure_schema() -> None:
    if not _pg():
        return
    try:
        with _conn() as c, c.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS notices (
                    id         TEXT PRIMARY KEY,
                    title      TEXT NOT NULL,
                    body       TEXT NOT NULL DEFAULT '',
                    level      TEXT NOT NULL DEFAULT 'info',
                    pinned     BOOLEAN NOT NULL DEFAULT FALSE,
                    author     TEXT NOT NULL DEFAULT '',
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
                """
            )
    except Exception:
        pass


def _store() -> dict[str, Any]:
    d = db.read_store()
    d.setdefault("notices", {})
    return d


def _row(r: tuple) -> dict[str, Any]:
    return {
        "id": r[0],
        "title": r[1],
        "body": r[2],
        "level": r[3],
        "pinned": bool(r[4]),
        "author": r[5],
        "created_at": r[6],
        "updated_at": r[7],
    }


def create(
    *, title: str, body: str, level: str = "info", pinned: bool = False, author: str = ""
) -> dict[str, Any]:
    nid = uuid.uuid4().hex
    now = int(time.time())
    if level not in ("info", "warning", "critical"):
        level = "info"
    record = {
        "id": nid, "title": title, "body": body, "level": level,
        "pinned": pinned, "author": author, "created_at": now, "updated_at": now,
    }
    if _pg():
        try:
            ensure_schema()
            with _conn() as c, c.cursor() as cur:
                cur.execute(
                    "INSERT INTO notices (id,title,body,level,pinned,author,created_at,updated_at)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (nid, title, body, level, pinned, author, now, now),
                )
            return record
        except Exception:
            pass
    with db._LOCK:
        data = _store()
        data["notices"][nid] = record
        db._write(data)
    return record


def list_all(limit: int = 100) -> list[dict[str, Any]]:
    if _pg():
        try:
            ensure_schema()
            with _conn() as c, c.cursor() as cur:
                cur.execute(
                    "SELECT id,title,body,level,pinned,author,created_at,updated_at"
                    " FROM notices ORDER BY pinned DESC, created_at DESC LIMIT %s",
                    (limit,),
                )
                return [_row(r) for r in cur.fetchall()]
        except Exception:
            pass
    items = list(_store()["notices"].values())
    items.sort(key=lambda n: (n.get("pinned", False), n.get("created_at", 0)), reverse=True)
    return items[:limit]


def get(notice_id: str) -> dict[str, Any] | None:
    if _pg():
        try:
            with _conn() as c, c.cursor() as cur:
                cur.execute(
                    "SELECT id,title,body,level,pinned,author,created_at,updated_at"
                    " FROM notices WHERE id=%s",
                    (notice_id,),
                )
                row = cur.fetchone()
                return _row(row) if row else None
        except Exception:
            pass
    return _store()["notices"].get(notice_id)


def update(notice_id: str, **fields: Any) -> dict[str, Any] | None:
    allowed = {"title", "body", "level", "pinned"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return get(notice_id)
    now = int(time.time())
    if _pg():
        try:
            sets = ", ".join(f"{k}=%s" for k in fields)
            with _conn() as c, c.cursor() as cur:
                cur.execute(
                    f"UPDATE notices SET {sets}, updated_at=%s WHERE id=%s",
                    (*fields.values(), now, notice_id),
                )
                if cur.rowcount == 0:
                    return None
            return get(notice_id)
        except Exception:
            pass
    with db._LOCK:
        data = _store()
        rec = data["notices"].get(notice_id)
        if not rec:
            return None
        rec.update(fields)
        rec["updated_at"] = now
        db._write(data)
        return rec


def delete(notice_id: str) -> bool:
    if _pg():
        try:
            with _conn() as c, c.cursor() as cur:
                cur.execute("DELETE FROM notices WHERE id=%s", (notice_id,))
                return cur.rowcount > 0
        except Exception:
            pass
    with db._LOCK:
        data = _store()
        if notice_id not in data["notices"]:
            return False
        del data["notices"][notice_id]
        db._write(data)
        return True