#!/usr/bin/env python3
"""tg - control CLI for the Telegram bridge (stdlib only)."""

import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
INBOX = os.path.join(DATA, "inbox.jsonl")
OUTBOX = os.path.join(DATA, "outbox.jsonl")
SENT = os.path.join(DATA, "sent.jsonl")
STATE = os.path.join(DATA, "state.json")
PIDFILE = os.path.join(BASE, "run", "watchdog.pid")
WORKERPID = os.path.join(BASE, "run", "bridge.pid")
LOGFILE = os.path.join(BASE, "logs", "bridge.log")
WLOG = os.path.join(BASE, "logs", "watchdog.log")
CONFIG = os.path.join(BASE, "config.json")
BRIDGE = os.path.join(BASE, "bridge.py")
WATCHDOG = os.path.join(BASE, "watchdog.py")


def out(*a):
    print(*a, flush=True)


def load(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


def read_jsonl(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    return rows


def append_jsonl(path, obj):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        f.flush()


def cfg():
    return load(CONFIG, {})


def api(c, method, payload=None, timeout=60):
    url = "https://api.telegram.org/bot%s/%s" % (c["bot_token"], method)
    data = urllib.parse.urlencode(payload or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read().decode("utf-8"))
    if not body.get("ok"):
        raise RuntimeError(body.get("description"))
    return body.get("result")


def split_text(t, limit=3800):
    if len(t) <= limit:
        return [t]
    parts, buf = [], ""
    for line in t.replace("\r\n", "\n").split("\n"):
        if len(buf) + len(line) + 1 > limit and buf:
            parts.append(buf)
            buf = line
        else:
            buf = (buf + "\n" + line) if buf else line
    if buf:
        parts.append(buf)
    return parts


def resolve_chat(c, explicit=None):
    if explicit:
        return explicit
    st = load(STATE, {})
    chat = (st.get("chats") or {}).get(c.get("owner_name"))
    if chat:
        return chat
    rows = read_jsonl(INBOX)
    for r in reversed(rows):
        if r.get("chat_id"):
            return r["chat_id"]
    return None


def _alive(path):
    if not os.path.exists(path):
        return None
    try:
        pid = int(open(path, encoding="utf-8").read().strip())
    except Exception:
        return None
    if pid <= 0:
        return None
    try:
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        ctypes.windll.kernel32.CloseHandle(handle)
        return pid
    except Exception:
        return pid


def pid_alive():
    return _alive(PIDFILE) or _alive(WORKERPID)


def _kill(pid):
    import ctypes
    h = ctypes.windll.kernel32.OpenProcess(1, False, pid)
    if not h:
        return False
    ctypes.windll.kernel32.TerminateProcess(h, 0)
    ctypes.windll.kernel32.CloseHandle(h)
    return True


def cmd_start(c, args):
    wd = _alive(PIDFILE)
    if wd:
        out("[tg] already running (watchdog pid=%s)" % wd)
        return 0
    for p in (PIDFILE, WORKERPID):
        try:
            os.remove(p)
        except OSError:
            pass
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0
    p = subprocess.Popen([sys.executable, "-X", "utf8", WATCHDOG], cwd=BASE, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=si)
    out("[tg] started watchdog pid=%s" % p.pid)
    for _ in range(20):
        time.sleep(1)
        if _alive(WORKERPID):
            break
    out("[tg] worker pid     = %s" % _alive(WORKERPID))
    if os.path.exists(LOGFILE):
        out("[tg] bridge log    = %s" % open(LOGFILE, encoding="utf-8").read().strip().splitlines()[-1])
    return 0


def cmd_stop(c, args):
    killed = []
    for path in (PIDFILE, WORKERPID):
        pid = _alive(path)
        if pid:
            _kill(pid)
            killed.append(pid)
        try:
            os.remove(path)
        except OSError:
            pass
    out("[tg] stopped: %s" % (", ".join(str(k) for k in killed) if killed else "nothing was running"))
    return 0


def cmd_status(c, args):
    wd = _alive(PIDFILE)
    wk = _alive(WORKERPID)
    st = load(STATE, {})
    rows = read_jsonl(INBOX)
    out("watchdog pid    : %s" % (wd or "stopped"))
    out("worker pid      : %s" % (wk or "stopped"))
    out("started_at      : %s" % st.get("started_at"))
    out("heartbeat       : %s" % st.get("heartbeat"))
    out("last_poll       : %s" % st.get("last_poll"))
    out("update offset   : %s" % st.get("offset"))
    out("bound chats     : %s" % json.dumps(st.get("chats") or {}, ensure_ascii=False))
    out("inbox messages  : %d" % len(rows))
    out("sent messages   : %d" % len(read_jsonl(SENT)))
    out("inbox file      : %s" % INBOX)
    return 0


def cmd_me(c, args):
    me = api(c, "getMe")
    wh = api(c, "getWebhookInfo")
    out("bot id       : %s" % me["id"])
    out("bot username : @%s" % me["username"])
    out("bot name     : %s" % me.get("first_name"))
    out("webhook url  : %s" % (wh.get("url") or "(none)"))
    out("pending      : %s" % wh.get("pending_update_count"))
    return 0


def cmd_send(c, args):
    text = " ".join(args).strip()
    if not text:
        out("[tg] nothing to send")
        return 1
    chat = resolve_chat(c, os.environ.get("TG_CHAT"))
    if not chat:
        out("[tg] no chat bound yet - send /start to the bot first")
        return 1
    sent = []
    for chunk in split_text(text):
        sent.append(api(c, "sendMessage", {"chat_id": str(chat), "text": chunk,
                                           "disable_web_page_preview": "true"}))
    for s in sent:
        append_jsonl(SENT, {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "chat_id": chat,
                            "text": s.get("text", ""), "message_id": s.get("message_id"),
                            "via": "cli"})
        out("[tg] delivered -> chat %s message_id=%s" % (chat, s.get("message_id")))
    return 0


def cmd_poll(c, args):
    rows = read_jsonl(INBOX)
    show_all = "--all" in args
    n = 20
    for a in args:
        if a.isdigit():
            n = int(a)
    rows = rows if show_all else rows[-n:]
    if not rows:
        out("=== TELEGRAM INBOX: empty (no message received yet) ===")
        return 0
    out("=== TELEGRAM INBOX  %d message(s)  file=%s ===" % (len(rows), INBOX))
    for r in rows:
        out("-" * 60)
        out("time    : %s" % r.get("ts"))
        out("from    : %s  chat_id=%s  msg_id=%s" % (r.get("user"), r.get("chat_id"), r.get("message_id")))
        out("content : %s" % (r.get("text") or "").replace("\n", "\n          "))
    out("-" * 60)
    out("=== end inbox ===")
    return 0


def cmd_wait(c, args):
    secs = 30
    if args and args[0].isdigit():
        secs = int(args[0])
    start = len(read_jsonl(INBOX))
    out("[tg] waiting up to %ds for a Telegram message ..." % secs)
    deadline = time.time() + secs
    while time.time() < deadline:
        rows = read_jsonl(INBOX)
        if len(rows) > start:
            for r in rows[start:]:
                out("[tg] received @%s: %s" % (r.get("user"), r.get("text")))
            return 0
        time.sleep(1)
    out("[tg] no message within %ds" % secs)
    return 1


def cmd_inbox_path(c, args):
    out(INBOX)
    return 0


def cmd_test(c, args):
    text = "\n".join([
        "✅ Telegram 通道自检通过",
        "bot     : @%s" % c["bot_username"],
        "owner   : %s" % c["owner_name"],
        "time    : %s" % time.strftime("%Y-%m-%d %H:%M:%S"),
        "host    : %s" % os.environ.get("COMPUTERNAME"),
        "source  : opencode bridge (D:\\AI\\tg)",
    ])
    return cmd_send(c, text.split("\n"))


CMDS = {
    "start": cmd_start, "stop": cmd_stop, "status": cmd_status, "me": cmd_me,
    "send": cmd_send, "poll": cmd_poll, "wait": cmd_wait,
    "test": cmd_test, "inbox-path": cmd_inbox_path,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        out("usage: tg.ps1 <start|stop|status|me|send <text>|poll [n] [--all]|wait <sec>|test|inbox-path>")
        return 0
    cmd = sys.argv[1].lower()
    if cmd not in CMDS:
        out("unknown command: %s" % cmd)
        return 1
    return CMDS[cmd](cfg(), sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main() or 0)