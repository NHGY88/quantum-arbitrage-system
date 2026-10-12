#!/usr/bin/env python3
"""Supervisor for bridge.py.

Keeps exactly one bridge.py worker alive:
  * single instance (named mutex) so duplicate watchdogs can't fight
  * restarts the worker if it exits
  * restarts it if its heartbeat goes stale - but only after a grace period,
    so a freshly spawned worker is never killed before its first heartbeat
"""

import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import time
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.join(BASE, "bridge.py")
RUN = os.path.join(BASE, "run")
PIDFILE = os.path.join(RUN, "watchdog.pid")
WORKERPID = os.path.join(RUN, "bridge.pid")
STATE = os.path.join(BASE, "data", "state.json")
LOGFILE = os.path.join(BASE, "logs", "watchdog.log")

STALE_SECONDS = 240
GRACE_SECONDS = 150
MUTEX_NAME = "Local\\tg_bridge_watchdog_v1"

os.makedirs(RUN, exist_ok=True)
os.makedirs(os.path.dirname(LOGFILE), exist_ok=True)

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.restype = wt.HANDLE
_kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    try:
        with open(LOGFILE, "a", encoding="utf-8") as f:
            f.write("%s [watchdog] %s\n" % (now(), msg))
    except Exception:
        pass


def acquire_single_instance():
    handle = _kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return None
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        return None
    return handle


def heartbeat_age():
    try:
        with open(STATE, "r", encoding="utf-8-sig") as f:
            st = json.load(f)
        ts = st.get("heartbeat")
        if not ts:
            return None
        return time.time() - time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))
    except Exception:
        return None


def main():
    mutex = acquire_single_instance()
    if mutex is None:
        log("another watchdog is already running, exiting")
        return 0

    with open(PIDFILE, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    log("watchdog started pid=%s" % os.getpid())

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    while True:
        log("spawning bridge.py")
        spawn_ts = time.time()
        try:
            proc = subprocess.Popen([sys.executable, "-X", "utf8", BRIDGE], cwd=BASE, env=env)
        except Exception as e:
            log("spawn failed: %s (retry in 10s)" % e)
            time.sleep(10)
            continue

        while proc.poll() is None:
            time.sleep(5)
            if time.time() - spawn_ts < GRACE_SECONDS:
                continue
            age = heartbeat_age()
            if age is not None and age > STALE_SECONDS:
                log("worker heartbeat stale (%.0fs), killing" % age)
                proc.kill()
                break
        rc = proc.poll()
        log("worker exited rc=%s, restarting in 5s" % rc)
        try:
            os.remove(WORKERPID)
        except OSError:
            pass
        time.sleep(5)


if __name__ == "__main__":
    sys.exit(main() or 0)
