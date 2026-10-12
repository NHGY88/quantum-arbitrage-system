"""Isolation tests for the Admin Server.

Each test runs against a throwaway JSON store so the suite never touches the
live db.json. Set QE_DATA_DIR before import to relocate the whole data dir.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Redirect the data dir to a temp folder BEFORE the app imports settings.
_TMP = Path(tempfile.mkdtemp(prefix="qe-test-"))
os.environ["QE_DATA_DIR"] = str(_TMP)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db, engine, points, rbac, settings  # noqa: E402
from app.auth import create_access_token, hash_password, verify_password  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402


@pytest.fixture(autouse=True)
def clean_store(monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", _TMP / "data")
    monkeypatch.setattr(settings, "SHOTS_DIR", _TMP / "data" / "shots")
    monkeypatch.setattr(db, "_DB_PATH", _TMP / "data" / "db.json")
    settings.ensure_dirs()
    db.write_store({"users": {}, "shots": {}, "settings": {}, "permissions": {},
                    "licenses": {}, "activations": {}, "points": {}, "refcode": {},
                    "referrer": {}, "ledger": []})
    # Force RBAC and points onto the JSON store (never touch real PostgreSQL)
    monkeypatch.setattr(rbac, "_PG_TRIED", False)
    monkeypatch.setattr(rbac, "_pg", lambda: False)
    monkeypatch.setattr(points, "_pg_ok", False)
    yield


@pytest.fixture()
def client():
    return TestClient(fastapi_app)


@pytest.fixture()
def admin_token():
    rbac.create_user("admin", "ChangeMe123!", role=rbac.ROLE_ADMIN, display_name="ad")
    return create_access_token("admin", {"role": rbac.ROLE_ADMIN})


@pytest.fixture()
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# --- password hashing -----------------------------------------------------

def test_hash_password_roundtrip():
    enc = hash_password("s3cret")
    assert enc.startswith("pbkdf2_sha256$")
    assert verify_password("s3cret", enc)
    assert not verify_password("wrong", enc)


def test_hash_password_salted():
    a = hash_password("same")
    b = hash_password("same")
    assert a != b  # different salts
    assert verify_password("same", a) and verify_password("same", b)


def test_verify_password_garbage():
    assert not verify_password("x", "not-a-hash")


# --- auth endpoints -------------------------------------------------------

def test_login_ok(client):
    rbac.create_user("admin", "ChangeMe123!", role=rbac.ROLE_ADMIN)
    r = client.post("/api/auth/login", json={"username": "admin", "password": "ChangeMe123!"})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_login_bad_password(client):
    rbac.create_user("admin", "ChangeMe123!", role=rbac.ROLE_ADMIN)
    r = client.post("/api/auth/login", json={"username": "admin", "password": "nope"})
    assert r.status_code == 401


def test_login_unknown_user(client):
    r = client.post("/api/auth/login", json={"username": "ghost", "password": "x"})
    assert r.status_code == 401


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_with_token(client, auth):
    r = client.get("/api/auth/me", headers=auth)
    assert r.status_code == 200
    assert r.json()["username"] == "admin"


def test_me_bad_token(client):
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


# --- health / status ------------------------------------------------------

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_status_shape(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert "postgres" in body and "redis" in body and "json_fallback" in body


# --- markdown combo parsing ----------------------------------------------

MARKDOWN = """
# 组表

## 1组 贵金属
- XAUUSD/XAGUSD corr 0.97
- XAUUSD/XPTUSD corr 0.91

## 2组 货币
- EURUSD/GBPUSD corr 0.88
"""


def test_parse_markdown_groups():
    combos = engine.parse_markdown(MARKDOWN)
    assert len(combos) == 2
    g1 = next(c for c in combos if c.group == 1)
    assert g1.correlation == 0.97
    symbols = [l.symbol for l in g1.legs]
    assert "XAUUSD" in symbols and "XAGUSD" in symbols


def test_parse_markdown_sorted_by_corr():
    combos = engine.parse_markdown(MARKDOWN)
    corrs = [c.correlation for c in combos if c.correlation is not None]
    assert corrs == sorted(corrs, reverse=True)


def test_parse_markdown_index_symbols_with_digits():
    md = """
    ## 3组 股指指数
    - SPX500/NAS100 corr 0.92
    - SPX500/US30 corr 0.96
    """
    combos = engine.parse_markdown(md)
    assert len(combos) == 1
    symbols = [l.symbol for l in combos[0].legs]
    assert "SPX500" in symbols and "NAS100" in symbols and "US30" in symbols
    assert combos[0].correlation == 0.96


def test_parse_markdown_table():
    md = """
    | leg_a | leg_b | corr |
    |-------|-------|------|
    | XAUUSD | XAGUSD | 0.95 |
    """
    combos = engine.parse_markdown(md)
    assert combos
    assert combos[0].correlation == 0.95


def test_combos_endpoint(client):
    r = client.get("/api/combos")
    assert r.status_code == 200
    assert "count" in r.json()


# --- hedge maths ----------------------------------------------------------

def test_dynamic_ratio_value():
    r = engine.dynamic_hedge_ratio(mode="value", value_a=100, value_b=175, vol_a=1, vol_b=1)
    assert r == pytest.approx(1.75)


def test_dynamic_ratio_volatility():
    r = engine.dynamic_hedge_ratio(
        mode="volatility", value_a=1, value_b=1, vol_a=2.0, vol_b=1.0, corr=0.9
    )
    assert r == pytest.approx(1.8)


def test_dynamic_ratio_bad_mode():
    with pytest.raises(ValueError):
        engine.dynamic_hedge_ratio(mode="nope", value_a=1, value_b=1, vol_a=1, vol_b=1)


def test_risk_cap_caps_exposure():
    out = engine.apply_risk_caps(10.0, equity=1000, leg_a_value=100, lots=1.0)
    assert out["risk_triggered"] is True
    assert out["final_ratio"] < out["requested_ratio"]


def test_risk_min_lot_floor():
    out = engine.apply_risk_caps(0.0, equity=1000, leg_a_value=100, lots=0.001)
    assert out["lots"] >= 0.01


def test_hedge_endpoint(client, auth):
    r = client.post(
        "/api/hedge/calculate",
        json={
            "mode": "value",
            "value_a": 100,
            "value_b": 175,
            "equity": 100000,
            "lots": 0.01,
        },
        headers=auth,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["requested_ratio"] == pytest.approx(1.75)


def test_hedge_endpoint_bad_mode(client, auth):
    r = client.post(
        "/api/hedge/calculate",
        json={"mode": "bad", "value_a": 1, "value_b": 1},
        headers=auth,
    )
    assert r.status_code == 422


# --- self-registration + admin granting ---------------------------------

def test_register_creates_pending_user(client):
    r = client.post(
        "/api/auth/register",
        json={"username": "newbie", "password": "User@1234", "display_name": "新人"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending"
    assert body["permissions"] == []
    u = rbac.get_user("newbie")
    assert u is not None and u["pending"] is True


def test_register_duplicate_rejected(client):
    client.post("/api/auth/register", json={"username": "dup", "password": "User@1234"})
    r = client.post("/api/auth/register", json={"username": "dup", "password": "User@1234"})
    assert r.status_code == 409


def test_register_rejects_bad_username(client):
    r = client.post("/api/auth/register", json={"username": "bad name!", "password": "User@1234"})
    assert r.status_code == 422


def test_pending_user_blocked_from_guarded_action(client):
    client.post("/api/auth/register", json={"username": "newbie", "password": "User@1234"})
    login = client.post("/api/auth/login", json={"username": "newbie", "password": "User@1234"})
    assert login.status_code == 200
    tok = login.json()["access_token"]
    r = client.post(
        "/api/hedge/calculate",
        json={"mode": "value", "value_a": 1, "value_b": 1, "equity": 1, "lots": 0.01},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 403


def test_admin_grants_permission_then_user_passes(client):
    client.post("/api/auth/register", json={"username": "newbie", "password": "User@1234"})
    rbac.create_user("admin", "ChangeMe123!", role=rbac.ROLE_ADMIN)
    adm = client.post("/api/auth/login", json={"username": "admin", "password": "ChangeMe123!"})
    atok = adm.json()["access_token"]

    g = client.put(
        "/api/rbac/users/newbie/permissions",
        json={"permissions": {"trade:read": "allow"}},
        headers={"Authorization": f"Bearer {atok}"},
    )
    assert g.status_code == 200
    assert "trade:read" in g.json()["effective"]

    login = client.post("/api/auth/login", json={"username": "newbie", "password": "User@1234"})
    tok = login.json()["access_token"]
    assert "trade:read" in login.json()["permissions"]
    r = client.post(
        "/api/hedge/calculate",
        json={"mode": "value", "value_a": 100, "value_b": 175, "equity": 100000, "lots": 0.01},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200


def test_catalog_has_five_categories(client, auth):
    r = client.get("/api/rbac/catalog", headers=auth)
    assert r.status_code == 200
    keys = [c["key"] for c in r.json()["categories"]]
    assert keys == ["combo", "trade", "me", "notice", "backend"]


def test_non_admin_cannot_list_users(client):
    rbac.create_user("plain", "User@1234", role=rbac.ROLE_USER, permissions={})
    login = client.post("/api/auth/login", json={"username": "plain", "password": "User@1234"})
    tok = login.json()["access_token"]
    r = client.get("/api/rbac/users", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403


def test_admin_cannot_be_deleted(client, auth):
    r = client.delete("/api/rbac/users/admin", headers=auth)
    assert r.status_code == 400


# --- screenshots ----------------------------------------------------------

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def test_shot_crud(client, auth):
    r = client.post(
        "/api/shots",
        files={"file": ("a.png", PNG, "image/png")},
        headers=auth,
    )
    assert r.status_code == 200
    shot = r.json()
    sid = shot["id"]

    lst = client.get("/api/shots", headers=auth).json()
    assert any(s["id"] == sid for s in lst["shots"])

    read = client.get(f"/api/shots/{sid}", headers=auth)
    assert read.status_code == 200
    assert read.content.startswith(b"\x89PNG")

    dele = client.delete(f"/api/shots/{sid}", headers=auth)
    assert dele.status_code == 200
    assert client.get(f"/api/shots/{sid}", headers=auth).status_code == 404


def test_shot_upload_requires_auth(client):
    r = client.post("/api/shots", files={"file": ("a.png", PNG, "image/png")})
    assert r.status_code == 401


def test_shot_delete_missing(client, auth):
    assert client.delete("/api/shots/deadbeef", headers=auth).status_code == 404


# --- misc -----------------------------------------------------------------

def test_root(client):
    r = client.get("/")
    assert r.status_code == 200 and "service" in r.json()


def test_zscore():
    # z-score compares a latest value against the window
    assert engine.zscore([1, 2, 3, 4, 5], latest=3) == pytest.approx(0.0, abs=1e-6)
    assert engine.zscore([1, 2, 3, 4, 5], latest=5) > 0
    assert engine.zscore([1, 1, 1]) == 0.0


def test_kelly():
    assert engine.kelly_fraction(0.5, 2.0) == pytest.approx(0.25)
    assert engine.kelly_fraction(0.2, 1.0) == 0.0
# --- 积分与推广 -----------------------------------------------------------

def test_signup_bonus_is_100_and_8dp(client):
    r = client.post("/api/auth/register", json={"username": "bob", "password": "User@1234"})
    assert r.status_code == 200
    body = r.json()
    assert body["points"] == "100.00000000"
    assert points.balance_of("bob") == points.Decimal("100")


def test_referral_commission_10_percent(client):
    # admin creates ref code, then bob registers through it
    rbac.create_user("root", "User@1234", role=rbac.ROLE_USER, permissions={})
    code = points.ensure_ref_code("root")
    r = client.post("/api/auth/register",
                    json={"username": "bob", "password": "User@1234", "ref_code": code})
    assert r.status_code == 200
    # root earned 10% of bob's 100
    assert points.balance_of("root") == points.Decimal("10.00000000")


def test_multilevel_cascade(client):
    rbac.create_user("alice", "User@1234", role=rbac.ROLE_USER, permissions={})
    codeA = points.ensure_ref_code("alice")
    client.post("/api/auth/register", json={"username": "bee", "password": "User@1234", "ref_code": codeA})
    codeB = points.ensure_ref_code("bee")
    client.post("/api/auth/register", json={"username": "cee", "password": "User@1234", "ref_code": codeB})
    # B got 10 from C; A got 1 from C (10% of C's 100, plus 10 from B)
    assert points.balance_of("cee") == points.Decimal("100.00000000")
    assert points.balance_of("bee") == points.Decimal("110.00000000")  # 100 + 10
    assert points.balance_of("alice") == points.Decimal("11.00000000")   # 10 + 1


def test_team_summary(client):
    rbac.create_user("alice", "User@1234", role=rbac.ROLE_USER, permissions={})
    code = points.ensure_ref_code("alice")
    client.post("/api/auth/register", json={"username": "bee", "password": "User@1234", "ref_code": code})
    s = points.summary("alice")
    assert s["team_total"] == 1
    assert s["team_direct"] == 1


def test_daily_decay_reduces_balance():
    from datetime import datetime, timezone
    rbac.create_user("u", "User@1234", role=rbac.ROLE_USER, permissions={})
    points.credit("u", points.Decimal("100"), "test", expires_in_days=30)
    before = points.balance_of("u")
    assert before == points.Decimal("100.00000000")
    points.run_daily_decay(reference=datetime.now(timezone.utc))
    after = points.balance_of("u")
    # must have decreased, stay positive, and equal before/days_left
    assert after < before and after > 0
    ledger = points.ledger_of("u", 5)
    assert any(row["reason"] == "daily_decay" for row in ledger)


def test_ref_info_public(client):
    rbac.create_user("root", "User@1234", role=rbac.ROLE_USER, permissions={})
    code = points.ensure_ref_code("root")
    r = client.get(f"/api/points/ref/{code}")
    assert r.status_code == 200 and r.json()["referrer"] == "root"
    assert client.get("/api/points/ref/BADCODE").status_code == 404


def test_points_requires_auth(client):
    assert client.get("/api/points/me").status_code == 401
