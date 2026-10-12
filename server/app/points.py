"""积分体系 + 推广（推荐）关系。

规则
----
1. 注册即赠送 100 积分，有效期 30 个自然日。
2. 每天 02:00 自动扣减：按「剩余积分 / 剩余天数」线性扣，30 天扣完。
3. 下线获得积分时，其上级按 10% 获得积分，**永久逐级、无级差**：
       B 注册 -> B +100，A +10
       C 通过 B 注册 -> C +100，B +10，A +1
4. 所有金额一律使用 Decimal，保留 8 位小数（禁止 float）。

数据表
------
app_users.points            当前积分余额（NUMERIC 30,8）
app_users.points_expires_at 积分到期时间
app_users.ref_code          本人的推广码
app_users.referrer          直接上级（注册时通过推广链接绑定）
user_refs                   闭包表，记录任意深度的上下级关系
points_ledger               积分流水（可审计）
"""

from __future__ import annotations

import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from . import db, settings

# --- 常量 -----------------------------------------------------------------

SCALE = Decimal("0.00000001")          # 8 位小数

def _dec_cfg(name: str, default: str) -> Decimal:
    try:
        return Decimal(str(settings.get(name, default)))
    except Exception:
        return Decimal(default)

SIGNUP_BONUS = _dec_cfg("POINTS_SIGNUP_BONUS", "100")
VALID_DAYS = int(settings.get_int("POINTS_VALID_DAYS", 30))
COMMISSION_RATE = _dec_cfg("POINTS_COMMISSION_RATE", "0.10")
MIN_PAYOUT = Decimal("0.00000001")      # 小于此值不分成，避免无意义流水
DECAY_HOUR = int(settings.get_int("POINTS_DECAY_HOUR", 2))  # 每天凌晨 2 点扣减

_CODE_ALPHABET = string.ascii_uppercase + string.digits
_pg_ok: bool | None = None


def q(value: Decimal | float | int | str) -> Decimal:
    """量化到 8 位小数。"""
    return Decimal(str(value)).quantize(SCALE, rounding=ROUND_HALF_UP)


def _conn():
    import psycopg  # type: ignore

    return psycopg.connect(settings.DATABASE_URL, connect_timeout=3)


def _pg() -> bool:
    global _pg_ok
    if _pg_ok is None:
        _pg_ok = db.check_postgres()
    return bool(_pg_ok)


def now() -> datetime:
    return datetime.now(timezone.utc)


# --- schema ---------------------------------------------------------------

def ensure_schema() -> None:
    if not _pg():
        return
    try:
        with _conn() as c, c.cursor() as cur:
            cur.execute(
                """
                ALTER TABLE app_users
                    ADD COLUMN IF NOT EXISTS points NUMERIC(30,8) NOT NULL DEFAULT 0,
                    ADD COLUMN IF NOT EXISTS points_expires_at TIMESTAMPTZ,
                    ADD COLUMN IF NOT EXISTS ref_code TEXT,
                    ADD COLUMN IF NOT EXISTS referrer TEXT
                """
            )
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS app_users_ref_code ON app_users(ref_code)")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_refs (
                    ancestor   TEXT NOT NULL,
                    descendant TEXT NOT NULL,
                    depth      INTEGER NOT NULL,
                    PRIMARY KEY (ancestor, descendant)
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS user_refs_desc ON user_refs(descendant, depth)")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS points_ledger (
                    id          TEXT PRIMARY KEY,
                    username    TEXT NOT NULL,
                    delta       NUMERIC(30,8) NOT NULL,
                    balance     NUMERIC(30,8) NOT NULL,
                    reason      TEXT NOT NULL,
                    source_user TEXT,
                    expires_at  TIMESTAMPTZ,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS ledger_user ON points_ledger(username, created_at DESC)")
    except Exception:
        pass


# --- JSON fallback store ---------------------------------------------------

def _store() -> dict[str, Any]:
    d = db.read_store()
    d.setdefault("points", {})
    d.setdefault("refcode", {})
    d.setdefault("referrer", {})
    d.setdefault("ledger", [])
    return d


# --- ref code --------------------------------------------------------------

def new_ref_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))


def ensure_ref_code(username: str) -> str:
    if _pg():
        try:
            ensure_schema()
            with _conn() as c, c.cursor() as cur:
                cur.execute("SELECT ref_code FROM app_users WHERE username=%s", (username,))
                row = cur.fetchone()
                code = row[0] if row else None
                if code:
                    return code
                code = new_ref_code()
                cur.execute(
                    "UPDATE app_users SET ref_code=%s WHERE username=%s", (code, username)
                )
                return code
        except Exception:
            pass
    d = _store()
    code = d["refcode"].get(username)
    if not code:
        code = new_ref_code()
        d["refcode"][username] = code
        db.write_store(d)
    return code


def resolve_ref(code: str) -> str | None:
    """推广码 -> 上级用户名。"""
    if not code:
        return None
    code = code.strip().upper()
    if _pg():
        try:
            ensure_schema()
            with _conn() as c, c.cursor() as cur:
                cur.execute("SELECT username FROM app_users WHERE UPPER(ref_code)=%s", (code,))
                row = cur.fetchone()
                return row[0] if row else None
        except Exception:
            pass
    for user, rc in _store()["refcode"].items():
        if str(rc).upper() == code:
            return user
    return None


# --- relationship graph ---------------------------------------------------

def bind_referral(child: str, parent: str | None) -> None:
    """绑定上级，并维护闭包表（child -> parent, parent's ancestors）。

    关键：父节点必须先有自环行 (parent,parent,0)，否则
    `SELECT ancestor FROM user_refs WHERE descendant=parent` 查不到任何行，
    导致子节点无法挂到父节点已有的祖先链上。
    """
    if not parent or parent == child:
        parent = None
    if _pg():
        try:
            ensure_schema()
            with _conn() as c, c.cursor() as cur:
                # ensure the parent has a self-row before we copy from it
                cur.execute(
                    "INSERT INTO user_refs (ancestor,descendant,depth) VALUES (%s,%s,0)"
                    " ON CONFLICT (ancestor,descendant) DO NOTHING",
                    (parent, parent),
                )
                # every account gets its own self-row too
                cur.execute(
                    "INSERT INTO user_refs (ancestor,descendant,depth) VALUES (%s,%s,0)"
                    " ON CONFLICT (ancestor,descendant) DO NOTHING",
                    (child, child),
                )
                cur.execute(
                    "UPDATE app_users SET referrer=%s WHERE username=%s", (parent, child)
                )
                if parent:
                    cur.execute(
                        """
                        INSERT INTO user_refs (ancestor,descendant,depth)
                        SELECT ancestor, %s, depth + 1 FROM user_refs WHERE descendant = %s
                        ON CONFLICT (ancestor,descendant) DO NOTHING
                        """,
                        (child, parent),
                    )
            return
        except Exception:
            pass
    d = _store()
    d["referrer"][child] = parent
    db.write_store(d)


def ensure_self_rows() -> int:
    """为所有账号补齐自环行 (u,u,0)，保证闭包表可查询。"""
    if not _pg():
        return 0
    try:
        ensure_schema()
        with _conn() as c, c.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_refs (ancestor,descendant,depth)
                SELECT username, username, 0 FROM app_users
                ON CONFLICT (ancestor,descendant) DO NOTHING
                """
            )
            return cur.rowcount or 0
    except Exception:
        return 0


def get_referrer(username: str) -> str | None:
    if _pg():
        try:
            ensure_schema()
            with _conn() as c, c.cursor() as cur:
                cur.execute("SELECT referrer FROM app_users WHERE username=%s", (username,))
                row = cur.fetchone()
                return row[0] if row else None
        except Exception:
            pass
    return _store()["referrer"].get(username)


def ancestors(username: str) -> list[str]:
    """从直接上级到最高级。"""
    if _pg():
        try:
            ensure_schema()
            with _conn() as c, c.cursor() as cur:
                cur.execute(
                    "SELECT ancestor FROM user_refs WHERE descendant=%s AND depth>0"
                    " ORDER BY depth",
                    (username,),
                )
                return [r[0] for r in cur.fetchall()]
        except Exception:
            pass
    chain, cur_u, guard = [], username, 0
    d = _store()
    while guard < 50:
        p = d["referrer"].get(cur_u)
        if not p:
            break
        chain.append(p)
        cur_u = p
        guard += 1
    return chain


def descendants(username: str) -> list[dict[str, Any]]:
    """全部下级（含层级）。"""
    if _pg():
        try:
            ensure_schema()
            with _conn() as c, c.cursor() as cur:
                cur.execute(
                    """
                    SELECT r.depth, u.username, u.display_name, u.points, u.enabled
                    FROM user_refs r JOIN app_users u ON u.username = r.descendant
                    WHERE r.ancestor = %s AND r.depth > 0
                    ORDER BY r.depth, u.created_at
                    """,
                    (username,),
                )
                return [
                    {
                        "depth": row[0],
                        "username": row[1],
                        "display_name": row[2],
                        "points": q(row[3]),
                        "enabled": bool(row[4]),
                    }
                    for row in cur.fetchall()
                ]
        except Exception:
            pass
    # JSON fallback: walk the parent map and record depth via BFS.
    parent_map = _store()["referrer"]
    users = _store()["users"]
    out: list[dict[str, Any]] = []
    frontier = [(c, 1) for c, p in parent_map.items() if p == username]
    while frontier:
        node, depth = frontier.pop(0)
        u = users.get(node, {})
        out.append(
            {
                "depth": depth,
                "username": node,
                "display_name": u.get("display_name", ""),
                "points": balance_of(node),
                "enabled": u.get("enabled", True),
            }
        )
        for c, p in parent_map.items():
            if p == node:
                frontier.append((c, depth + 1))
    out.sort(key=lambda x: (x["depth"], x["username"]))
    return out


# --- ledger ---------------------------------------------------------------

def _ledger_add(
    username: str, delta: Decimal, balance: Decimal, reason: str,
    source_user: str | None, expires_at: datetime | None,
) -> None:
    if _pg():
        try:
            with _conn() as c, c.cursor() as cur:
                cur.execute(
                    "INSERT INTO points_ledger (id,username,delta,balance,reason,"
                    "source_user,expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (uuid.uuid4().hex, username, delta, balance, reason, source_user, expires_at),
                )
            return
        except Exception:
            pass
    d = _store()
    d["ledger"].append(
        {
            "id": uuid.uuid4().hex,
            "username": username,
            "delta": str(delta),
            "balance": str(balance),
            "reason": reason,
            "source_user": source_user,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "created_at": now().isoformat(),
        }
    )
    db.write_store(d)


def _set_balance(username: str, balance: Decimal, expires_at: datetime | None) -> None:
    if _pg():
        try:
            with _conn() as c, c.cursor() as cur:
                cur.execute(
                    "UPDATE app_users SET points=%s, points_expires_at=%s WHERE username=%s",
                    (balance, expires_at, username),
                )
            return
        except Exception:
            pass
    d = _store()
    rec = d["points"].setdefault(username, {"balance": "0", "expires_at": None})
    rec["balance"] = str(balance)
    rec["expires_at"] = expires_at.isoformat() if expires_at else None
    db.write_store(d)


def balance_of(username: str) -> Decimal:
    if _pg():
        try:
            ensure_schema()
            with _conn() as c, c.cursor() as cur:
                cur.execute("SELECT points FROM app_users WHERE username=%s", (username,))
                row = cur.fetchone()
                return q(row[0]) if row and row[0] is not None else q(0)
        except Exception:
            pass
    rec = _store()["points"].get(username)
    return q(rec["balance"]) if rec else q(0)


def expires_of(username: str) -> datetime | None:
    if _pg():
        try:
            with _conn() as c, c.cursor() as cur:
                cur.execute(
                    "SELECT points_expires_at FROM app_users WHERE username=%s", (username,)
                )
                row = cur.fetchone()
                return row[0] if row else None
        except Exception:
            pass
    rec = _store()["points"].get(username)
    if not rec or not rec.get("expires_at"):
        return None
    try:
        return datetime.fromisoformat(rec["expires_at"])
    except ValueError:
        return None


# --- credit / commission ---------------------------------------------------

def credit(
    username: str, amount: Decimal, reason: str, *,
    source_user: str | None = None, expires_in_days: int | None = VALID_DAYS,
    cascade: bool = True,
) -> dict[str, Any]:
    """给用户加积分，并按 10% 逐级给上级返佣。"""
    amount = q(amount)
    if amount <= 0:
        return {"credited": "0", "balance": str(balance_of(username))}

    cur = balance_of(username)
    expires = expires_of(username)
    if expires_in_days:
        base = now() + timedelta(days=expires_in_days)
        # 续期取较晚者，避免覆盖更长的有效期
        expires = base if (expires is None or base > expires) else expires

    new_balance = q(cur + amount)
    _set_balance(username, new_balance, expires)
    _ledger_add(username, amount, new_balance, reason, source_user, expires)

    commissions: list[dict[str, Any]] = []
    if cascade:
        # 逐级分成：每一级都拿「上一级分成金额」的 10%
        #   下线 +100 -> 直接上级 +10 -> 上级的上级 +1 -> ...
        # 与用户表述一致："B 就是 10 个，那么 A 就是一个 10%"
        passed = amount
        for anc in ancestors(username):
            share = q(passed * COMMISSION_RATE)
            if share < MIN_PAYOUT:
                break
            abal = balance_of(anc)
            aexp = expires_of(anc)
            anew = q(abal + share)
            _set_balance(anc, anew, aexp)
            _ledger_add(anc, share, anew, f"commission:{reason}", username, aexp)
            commissions.append({"to": anc, "amount": str(share), "balance": str(anew)})
            passed = share  # 传给上一级的是这一级的分成金额

    return {
        "credited": str(amount),
        "balance": str(new_balance),
        "expires_at": expires.isoformat() if expires else None,
        "commissions": commissions,
    }


def spend(username: str, amount: Decimal, reason: str) -> bool:
    """扣减积分；不足则返回 False。"""
    amount = q(amount)
    cur = balance_of(username)
    if cur < amount:
        return False
    new = q(cur - amount)
    _set_balance(username, new, expires_of(username))
    _ledger_add(username, -amount, new, reason, None, expires_of(username))
    return True


# --- daily decay -----------------------------------------------------------

def run_daily_decay(reference: datetime | None = None) -> dict[str, Any]:
    """每天 02:00 执行：按剩余积分/剩余天数 线性扣减。"""
    ref = reference or now()
    touched = 0
    total_deducted = q(0)
    pairs: list[tuple[str, Decimal, datetime]] = []

    if _pg():
        try:
            ensure_schema()
            with _conn() as c, c.cursor() as cur:
                cur.execute(
                    "SELECT username, points, points_expires_at FROM app_users"
                    " WHERE points > 0 AND points_expires_at IS NOT NULL"
                    " AND points_expires_at > %s",
                    (ref,),
                )
                pairs = [(r[0], q(r[1]), r[2]) for r in cur.fetchall()]
        except Exception:
            pairs = []
    if not pairs:
        d = _store()
        for user, rec in d["points"].items():
            try:
                exp = datetime.fromisoformat(rec["expires_at"]) if rec.get("expires_at") else None
            except ValueError:
                exp = None
            bal = q(rec.get("balance", "0"))
            if exp and exp > ref and bal > 0:
                pairs.append((user, bal, exp))

    for username, bal, exp in pairs:
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        days_left = max(1, (exp - ref).days)
        deduct = q(bal / days_left)
        if deduct <= 0:
            continue
        new = q(bal - deduct)
        if new < 0:
            new = q(0)
        _set_balance(username, new, exp)
        _ledger_add(username, -deduct, new, "daily_decay", None, exp)
        touched += 1
        total_deducted = q(total_deducted + deduct)

    return {"touched": touched, "deducted": str(total_deducted), "at": ref.isoformat()}


def seconds_until_next_decay(reference: datetime | None = None) -> int:
    ref = reference or now()
    target = ref.replace(hour=DECAY_HOUR, minute=0, second=0, microsecond=0)
    if target <= ref:
        target += timedelta(days=1)
    return int((target - ref).total_seconds())


# --- views ----------------------------------------------------------------

def summary(username: str) -> dict[str, Any]:
    bal = balance_of(username)
    exp = expires_of(username)
    desc = descendants(username)
    direct = [d for d in desc if d["depth"] == 1]
    return {
        "username": username,
        "points": str(bal),
        "expires_at": exp.isoformat() if exp else None,
        "days_left": max(0, (exp - now()).days) if exp else 0,
        "ref_code": ensure_ref_code(username),
        "referrer": get_referrer(username),
        "ancestors": ancestors(username),
        "team_total": len(desc),
        "team_direct": len(direct),
        "team_points": str(q(sum((d["points"] for d in desc), Decimal(0)))),
        "team": desc,
    }


def ledger_of(username: str, limit: int = 50) -> list[dict[str, Any]]:
    if _pg():
        try:
            with _conn() as c, c.cursor() as cur:
                cur.execute(
                    "SELECT delta,balance,reason,source_user,created_at FROM points_ledger"
                    " WHERE username=%s ORDER BY created_at DESC LIMIT %s",
                    (username, limit),
                )
                return [
                    {
                        "delta": str(q(r[0])),
                        "balance": str(q(r[1])),
                        "reason": r[2],
                        "source_user": r[3],
                        "created_at": r[4].isoformat() if r[4] else None,
                    }
                    for r in cur.fetchall()
                ]
        except Exception:
            pass
    rows = [r for r in _store()["ledger"] if r["username"] == username]
    rows.reverse()
    return rows[:limit]
