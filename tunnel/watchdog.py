"""Supervisor for the public Cloudflare tunnel.

Keeps exactly one `cloudflared` quick tunnel alive and publishes the current
public URL to data/tunnel_url.txt so downstream tooling (and the user) can
always find it without digging through logs.
"""

import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
RUN = BASE / "run"
LOGDIR = BASE / "logs"
URLFILE = BASE / "data" / "tunnel_url.txt"
STATUSFILE = BASE / "data" / "tunnel_status.json"
CF = Path(r"D:\AI\downloads\cloudflared.exe")
TARGET = os.environ.get("TUNNEL_TARGET", "http://127.0.0.1:3000")
STALE_SECONDS = 180

RUN.mkdir(exist_ok=True)
LOGDIR.mkdir(parents=True, exist_ok=True)
URLFILE.parent.mkdir(parents=True, exist_ok=True)

_url_re = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def log(msg: str) -> None:
    with open(LOGDIR / "tunnel-watchdog.log", "a", encoding="utf-8") as f:
        f.write("%s %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))


def read_url() -> str:
    try:
        return URLFILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def publish(url: str, pid: int | None) -> None:
    URLFILE.write_text(url + "\n", encoding="utf-8")
    STATUSFILE.write_text(
        json.dumps(
            {
                "url": url,
                "pid": pid,
                "target": TARGET,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def spawn() -> subprocess.Popen:
    out = open(LOGDIR / "cloudflared.log", "a", encoding="utf-8")
    return subprocess.Popen(
        [str(CF), "tunnel", "--no-autoupdate", "--url", TARGET],
        stdout=out,
        stderr=subprocess.STDOUT,
        cwd=str(BASE),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def wait_for_url(proc: subprocess.Popen, timeout: float = 60.0) -> str:
    """Poll cloudflared's log for the assigned trycloudflare URL."""
    logfile = LOGDIR / "cloudflared.log"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return ""
        try:
            text = logfile.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        m = _url_re.search(text)
        if m:
            return m.group(0)
        time.sleep(2)
    return ""


def main() -> int:
    log("tunnel watchdog start target=%s" % TARGET)
    last_url = ""
    while True:
        proc = spawn()
        url = wait_for_url(proc)
        if url:
            publish(url, proc.pid)
            last_url = url
            log("tunnel up url=%s pid=%s" % (url, proc.pid))
        else:
            log("tunnel failed to report a URL; restarting in 5s")
            try:
                proc.kill()
            except OSError:
                pass
            time.sleep(5)
            continue

        started = time.time()
        while proc.poll() is None:
            time.sleep(5)
            if time.time() - started > STALE_SECONDS and read_url() != last_url:
                # someone else republished; assume this instance is redundant
                break
        log("tunnel exited rc=%s; restarting in 3s" % proc.poll())
        time.sleep(3)


if __name__ == "__main__":
    raise SystemExit(main())
