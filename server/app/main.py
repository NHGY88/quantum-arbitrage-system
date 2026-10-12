"""Admin Server (FastAPI) - Port 8000.

Endpoint surface:
  GET  /health                  liveness
  GET  /api/status              datastore status (pg / redis / json)
  POST /api/auth/login          { username, password } -> { access_token }
  GET  /api/auth/me             current user
  GET  /api/combos              parsed hedge combos from Markdown
  POST /api/hedge/calculate     dynamic hedge ratio + risk caps
  POST /api/shots               upload screenshot (multipart)
  GET  /api/shots               list screenshots
  GET  /api/shots/{id}          read screenshot bytes
  DELETE /api/shots/{id}        delete screenshot
"""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import db, engine, licensing, notices, points, rbac, settings
from .auth import create_access_token, decode_token, verify_password

async def _decay_scheduler() -> None:
    """Background loop: run the 02:00 points decay once per day."""
    while True:
        try:
            wait = points.seconds_until_next_decay()
            await asyncio.sleep(wait)
            result = points.run_daily_decay()
            print(f"[points] daily decay: {result}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # never let the scheduler die
            print(f"[points] decay error: {exc}")
            await asyncio.sleep(300)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.ensure_dirs()
    rbac.ensure_schema()
    points.ensure_schema()
    # The super-admin is the highest-privilege account; everything else is
    # created and granted by this account through the permission console.
    rbac.create_user(
        settings.SEED_USERNAME,
        settings.SEED_PASSWORD,
        role=rbac.ROLE_ADMIN,
        display_name="最高权限管理员",
    )
    task = asyncio.create_task(_decay_scheduler())
    try:
        # repair closure table: every account needs a (u,u,0) self row
        points.ensure_self_rows()
    except Exception as exc:
        print(f"[points] self-row repair failed: {exc}")
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(
    title="Quantum Arbitrage - Admin Server",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_STARTED_AT = time.time()


# --- auth -----------------------------------------------------------------

class LoginIn(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


def _require_user(request: Request, authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = decode_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid or expired token")

    username = claims.get("sub", "")
    user = rbac.get_user(username)
    if not user or not user.get("enabled", True):
        raise HTTPException(status_code=401, detail="user not found or disabled")

    # Optional license gate (Phase 7). When LICENSE_REQUIRED=true, a valid
    # license key must be presented via X-License-Key on every call.
    if LICENSE_REQUIRED:
        lic = request.headers.get("x-license-key")
        if not lic:
            raise HTTPException(status_code=402, detail="missing X-License-Key")
        result = licensing.validate(lic, claims.get("machine") or licensing.fingerprint())
        if not result.get("valid"):
            raise HTTPException(
                status_code=402,
                detail=f"license rejected: {result.get('code')} - {result.get('message')}",
            )

    return {
        "username": user["username"],
        "role": user.get("role", "user"),
        "display_name": user.get("display_name", ""),
        "permissions": user.get("effective", []),
    }


def _require_super(user: dict = Depends(_require_user)) -> dict:
    if not rbac.is_super(user.get("role", "")):
        raise HTTPException(status_code=403, detail="仅最高权限管理员可操作")
    return user


@app.post("/api/auth/login")
def login(payload: LoginIn):
    user = rbac.verify_user_password(payload.username, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="invalid credentials")
    perms = rbac.effective_permissions(user["role"], rbac.get_permissions(user["username"]))
    token = create_access_token(user["username"], {"role": user["role"], "machine": licensing.fingerprint()})
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": settings.TOKEN_TTL_SECONDS,
        "username": user["username"],
        "role": user["role"],
        "permissions": perms,
    }


@app.get("/api/auth/me")
def me(user: dict = Depends(_require_user)):
    return user


# --- health / status ------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "uptime_s": round(time.time() - _STARTED_AT, 1)}


@app.get("/api/status")
def status():
    pg = db.check_postgres()
    rd = db.check_redis()
    return {
        "app": settings.APP_NAME,
        "postgres": pg,
        "redis": rd,
        "json_fallback": True,
        "db_path": str(settings.DATA_DIR / "db.json"),
        "errors": {k: v for k, v in db.LAST_ERROR.items() if v},
    }


# --- combos / engine ------------------------------------------------------

@app.get("/api/combos")
def combos(group: int | None = None):
    parsed = engine.parse_markdown_dir(settings.COMBOS_DIR)
    if group is not None:
        parsed = [c for c in parsed if c.group == group]
    return {"count": len(parsed), "combos": [c.to_dict() for c in parsed]}


class HedgeIn(BaseModel):
    mode: str = Field(..., pattern="^(value|margin|volatility)$")
    value_a: float
    value_b: float
    vol_a: float = 1.0
    vol_b: float = 1.0
    corr: float = 1.0
    equity: float = 10_000.0
    lots: float = 0.01


@app.post("/api/hedge/calculate")
def hedge_calculate(payload: HedgeIn, user: dict = Depends(_require_user)):
    rbac.require_permission(user, "trade:read")
    try:
        ratio = engine.dynamic_hedge_ratio(
            mode=payload.mode,
            value_a=payload.value_a,
            value_b=payload.value_b,
            vol_a=payload.vol_a,
            vol_b=payload.vol_b,
            corr=payload.corr,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    caps = engine.apply_risk_caps(
        ratio,
        equity=payload.equity,
        leg_a_value=payload.value_a,
        lots=payload.lots,
    )
    return {"mode": payload.mode, **caps}


# --- screenshots ----------------------------------------------------------

@app.post("/api/shots")
async def upload_shot(file: UploadFile = File(...), user: dict = Depends(_require_user)):
    rbac.require_permission(user, "combo:read")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="empty file")
    shot_id = uuid.uuid4().hex
    path = db.shot_file_path(shot_id)
    settings.ensure_dirs()
    path.write_bytes(content)
    record = {
        "id": shot_id,
        "filename": file.filename or f"{shot_id}.png",
        "size": len(content),
        "content_type": file.content_type or "image/png",
        "uploaded_by": user["username"],
        "created_at": int(time.time()),
    }
    db.put_shot(shot_id, record)
    return record


@app.get("/api/shots")
def list_shots(user: dict = Depends(_require_user)):
    return {"shots": db.list_shots()}


@app.get("/api/shots/{shot_id}")
def read_shot(shot_id: str, user: dict = Depends(_require_user)):
    record = db.get_shot(shot_id)
    if not record:
        raise HTTPException(status_code=404, detail="shot not found")
    path = db.shot_file_path(shot_id)
    if not path.exists():
        raise HTTPException(status_code=410, detail="shot file missing")
    return FileResponse(path, media_type=record.get("content_type", "image/png"))


@app.delete("/api/shots/{shot_id}")
def remove_shot(shot_id: str, user: dict = Depends(_require_user)):
    rbac.require_permission(user, "combo:delete")
    path = db.shot_file_path(shot_id)
    ok = db.delete_shot(shot_id)
    if not ok:
        raise HTTPException(status_code=404, detail="shot not found")
    try:
        path.unlink()
    except OSError:
        pass
    return JSONResponse({"deleted": True, "id": shot_id})


@app.get("/")
def root():
    return {
        "service": settings.APP_NAME,
        "docs": "/docs",
        "health": "/health",
    }


# --- RBAC: user & permission management (super-admin only) ---------------

class UserCreateIn(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=4)
    role: str = "user"
    display_name: str = ""
    permissions: list[str] | dict = Field(default_factory=list)


class RegisterIn(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=6)
    display_name: str = ""
    ref_code: str = ""


@app.post("/api/auth/register")
def register(payload: RegisterIn):
    """Self-service signup.

    New accounts start with role=user and ZERO permissions ('pending' state).
    The super-admin then grants what each person needs from the permission
    console; until then the account can log in but every guarded action is
    refused with 403.
    """
    username = payload.username.strip()
    if not username.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(status_code=422, detail="用户名只能包含字母、数字、下划线和短横线")
    if rbac.get_user(username):
        raise HTTPException(status_code=409, detail="该用户名已被注册")

    points.ensure_schema()
    parent = points.resolve_ref(payload.ref_code)

    created = rbac.create_user(
        username,
        payload.password,
        role=rbac.ROLE_USER,
        display_name=payload.display_name or username,
        permissions={},          # nothing granted until an admin says so
        enabled=True,
    )
    # 绑定推广上级
    if parent:
        points.bind_referral(username, parent)
    # 赠送注册积分 + 上级 10% 返佣
    grant = points.credit(
        username, points.SIGNUP_BONUS, "signup_bonus",
        expires_in_days=points.VALID_DAYS,
    )
    return {
        "username": username,
        "role": rbac.ROLE_USER,
        "status": "pending",
        "message": "注册成功，等待管理员授权后即可使用完整功能",
        "permissions": [],
        "referrer": parent,
        "points": grant["balance"],
        "points_expires_at": grant["expires_at"],
        "ref_code": points.ensure_ref_code(username),
        "commissions": grant.get("commissions", []),
    }


class PermsSetIn(BaseModel):
    permissions: dict[str, str] = Field(default_factory=dict)


class ProfileIn(BaseModel):
    display_name: str = Field("", max_length=64)


@app.put("/api/auth/profile")
def update_profile(payload: ProfileIn, user: dict = Depends(_require_user)):
    """Self-service profile edit (own account only)."""
    rbac.require_permission(user, "me:write")
    existing = rbac.get_user(user["username"])
    if not existing:
        raise HTTPException(status_code=404, detail="user not found")
    rbac.set_display_name(user["username"], payload.display_name.strip())
    refreshed = rbac.get_user(user["username"]) or {}
    return {
        "username": user["username"],
        "display_name": refreshed.get("display_name", ""),
        "updated": True,
    }


@app.get("/api/rbac/catalog")
def rbac_catalog(user: dict = Depends(_require_user)):
    return rbac.catalog()


@app.get("/api/rbac/users")
def rbac_users(user: dict = Depends(_require_super)):
    return {"users": rbac.list_users()}


@app.post("/api/rbac/users")
def rbac_create_user(payload: UserCreateIn, user: dict = Depends(_require_super)):
    if payload.role == rbac.ROLE_ADMIN:
        raise HTTPException(status_code=400, detail="不能通过此接口再创建管理员")
    try:
        created = rbac.create_user(
            payload.username,
            payload.password,
            role=payload.role,
            display_name=payload.display_name,
            permissions=payload.permissions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    created.pop("password_hash", None)
    return created


@app.put("/api/rbac/users/{username}/permissions")
def rbac_set_permissions(username: str, payload: PermsSetIn, user: dict = Depends(_require_super)):
    target = rbac.get_user(username)
    if not target:
        raise HTTPException(status_code=404, detail="user not found")
    if target.get("role") == rbac.ROLE_ADMIN:
        raise HTTPException(status_code=400, detail="管理员权限不可修改")
    mapping = rbac.set_permissions(username, payload.permissions)
    refreshed = rbac.get_user(username) or {}
    return {
        "username": username,
        "permissions": mapping,
        "effective": refreshed.get("effective", []),
    }


@app.patch("/api/rbac/users/{username}")
def rbac_update_user(username: str, payload: dict, user: dict = Depends(_require_super)):
    target = rbac.get_user(username)
    if not target:
        raise HTTPException(status_code=404, detail="user not found")
    if target.get("role") == rbac.ROLE_ADMIN:
        raise HTTPException(status_code=400, detail="管理员账号不可修改")
    updates = {}
    for key in ("role", "display_name", "enabled"):
        if key in payload:
            updates[key] = payload[key]
    if "password" in payload and payload["password"]:
        updates["password"] = payload["password"]
    if not updates:
        raise HTTPException(status_code=422, detail="没有可更新字段")
    created = rbac.create_user(
        username,
        updates.pop("password", "") or target.get("_hash", "") or "x",
        role=updates.get("role", target.get("role", "user")),
        display_name=updates.get("display_name", target.get("display_name", "")),
        permissions=target.get("permissions", {}),
        enabled=updates.get("enabled", target.get("enabled", True)),
    )
    return {k: v for k, v in created.items() if k != "password_hash"}


@app.delete("/api/rbac/users/{username}")
def rbac_delete_user(username: str, user: dict = Depends(_require_super)):
    target = rbac.get_user(username)
    if not target:
        raise HTTPException(status_code=404, detail="user not found")
    if target.get("role") == rbac.ROLE_ADMIN:
        raise HTTPException(status_code=400, detail="管理员账号不可删除")
    rbac.set_permissions(username, {})
    if rbac._pg():
        try:
            with rbac._conn() as c, c.cursor() as cur:
                cur.execute("DELETE FROM app_users WHERE username=%s", (username,))
        except Exception:
            pass
    data = rbac._store()
    if username in data["users"]:
        del data["users"][username]
        data["permissions"].pop(username, None)
        rbac.save_store(data)
    return {"deleted": True, "username": username}


# --- Phase 7: licensing ---------------------------------------------------

LICENSE_REQUIRED = settings.get_bool("LICENSE_REQUIRED", False)


class LicenseCreateIn(BaseModel):
    label: str = ""
    plan: str = "pro"
    max_machines: int = Field(1, ge=1, le=100)
    days: int | None = 365
    notes: str = ""


class LicenseActivateIn(BaseModel):
    key: str = Field(..., min_length=4)
    fingerprint: str | None = None
    meta: dict = Field(default_factory=dict)


@app.get("/api/licenses")
def licenses_list(user: dict = Depends(_require_user)):
    return {"licenses": licensing.list_licenses(), "provider": licensing.PROVIDER}


@app.post("/api/licenses")
def licenses_create(payload: LicenseCreateIn, user: dict = Depends(_require_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    return licensing.create_license(
        label=payload.label,
        plan=payload.plan,
        max_machines=payload.max_machines,
        days=payload.days,
        notes=payload.notes,
    )


@app.post("/api/licenses/activate")
def licenses_activate(payload: LicenseActivateIn):
    fp = payload.fingerprint or licensing.fingerprint()
    return licensing.activate(payload.key, fp, payload.meta)


@app.post("/api/licenses/validate")
def licenses_validate(payload: LicenseActivateIn):
    fp = payload.fingerprint or licensing.fingerprint()
    return licensing.validate(payload.key, fp)


@app.post("/api/licenses/{license_id}/status")
def licenses_status(license_id: str, status: str, user: dict = Depends(_require_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    try:
        ok = licensing.set_status(license_id, status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not ok:
        raise HTTPException(status_code=404, detail="license not found")
    return {"id": license_id, "status": status}


@app.delete("/api/licenses/{license_id}")
def licenses_revoke(license_id: str, user: dict = Depends(_require_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    if not licensing.revoke(license_id):
        raise HTTPException(status_code=404, detail="license not found")
    return {"revoked": True, "id": license_id}


# --- 积分与推广（points / referral）--------------------------------------

@app.get("/api/points/me")
def points_me(user: dict = Depends(_require_user)):
    return points.summary(user["username"])


@app.get("/api/points/team")
def points_team(user: dict = Depends(_require_user)):
    return points.summary(user["username"])


@app.get("/api/points/ledger")
def points_ledger(user: dict = Depends(_require_user), limit: int = 50):
    return {"ledger": points.ledger_of(user["username"], min(limit, 200))}


@app.get("/api/points/ref/{code}")
def points_ref_info(code: str):
    """公开接口：校验推广码是否有效（注册页用）。"""
    owner = points.resolve_ref(code)
    if not owner:
        raise HTTPException(status_code=404, detail="推广码无效")
    return {"valid": True, "code": code.strip().upper(), "referrer": owner}


class PointsGrantIn(BaseModel):
    username: str
    amount: float = Field(..., gt=0)
    reason: str = "manual_grant"


@app.post("/api/points/grant")
def points_grant(payload: PointsGrantIn, user: dict = Depends(_require_super)):
    from decimal import Decimal

    return points.credit(
        payload.username,
        Decimal(str(payload.amount)),
        payload.reason,
        expires_in_days=points.VALID_DAYS,
    )


@app.post("/api/points/decay/run")
def points_decay_now(user: dict = Depends(_require_super)):
    return points.run_daily_decay()


# --- 公告（notice）--------------------------------------------------------

class NoticeIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    body: str = ""
    level: str = "info"
    pinned: bool = False


class NoticePatchIn(BaseModel):
    title: str | None = None
    body: str | None = None
    level: str | None = None
    pinned: bool | None = None


@app.get("/api/notices")
def notices_list(user: dict = Depends(_require_user), limit: int = 100):
    rbac.require_permission(user, "notice:read")
    return {"notices": notices.list_all(min(limit, 200))}


@app.post("/api/notices")
def notices_create(payload: NoticeIn, user: dict = Depends(_require_user)):
    rbac.require_permission(user, "notice:write")
    return notices.create(
        title=payload.title,
        body=payload.body,
        level=payload.level,
        pinned=payload.pinned,
        author=user["username"],
    )


@app.get("/api/notices/{notice_id}")
def notices_get(notice_id: str, user: dict = Depends(_require_user)):
    rbac.require_permission(user, "notice:read")
    rec = notices.get(notice_id)
    if not rec:
        raise HTTPException(status_code=404, detail="公告不存在")
    return rec


@app.patch("/api/notices/{notice_id}")
def notices_patch(notice_id: str, payload: NoticePatchIn, user: dict = Depends(_require_user)):
    rbac.require_permission(user, "notice:manage")
    fields = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    rec = notices.update(notice_id, **fields)
    if not rec:
        raise HTTPException(status_code=404, detail="公告不存在")
    return rec


@app.delete("/api/notices/{notice_id}")
def notices_delete(notice_id: str, user: dict = Depends(_require_user)):
    rbac.require_permission(user, "notice:manage")
    if not notices.delete(notice_id):
        raise HTTPException(status_code=404, detail="公告不存在")
    return {"deleted": True, "id": notice_id}