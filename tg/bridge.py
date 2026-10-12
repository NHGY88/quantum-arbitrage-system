#!/usr/bin/env python3
"""Telegram <-> OpenCode bridge daemon (stdlib only).

Responsibilities
  1. long-poll Telegram Bot API (getUpdates)
  2. append every inbound message to data/inbox.jsonl
  3. flush data/outbox.jsonl -> Telegram sendMessage
  4. keep data/state.json (last update_id, chat bindings, cursor offsets)

All state lives next to this file on D:\\AI\\tg
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
LOGS = os.path.join(BASE, "logs")
RUN = os.path.join(BASE, "run")
CONFIG = os.path.join(BASE, "config.json")
INBOX = os.path.join(DATA, "inbox.jsonl")
OUTBOX = os.path.join(DATA, "outbox.jsonl")
SENT = os.path.join(DATA, "sent.jsonl")
STATE = os.path.join(DATA, "state.json")
LOGFILE = os.path.join(LOGS, "bridge.log")
PIDFILE = os.path.join(RUN, "bridge.pid")

for d in (DATA, LOGS, RUN):
    os.makedirs(d, exist_ok=True)


def now():
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def log(msg, level="INFO"):
    line = f"{now()} [{level}] {msg}"
    try:
        with open(LOGFILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    if level in ("ERROR", "WARN"):
        print(line, flush=True)


def load_config():
    with open(CONFIG, "r", encoding="utf-8") as f:
        return json.load(f)


def load_state():
    if os.path.exists(STATE):
        try:
            with open(STATE, "r", encoding="utf-8-sig") as f:
                st = json.load(f)
            if isinstance(st, dict) and st.get("offset"):
                return st
            state = st if isinstance(st, dict) else {}
        except Exception:
            state = {}
        # corrupt / partial state: rebuild what we can from the inbox
        rebuilt = _rebuild_from_inbox(state)
        log("state.json was corrupt, rebuilt: offset=%s" % rebuilt.get("offset"), "WARN")
        return rebuilt
    return {"offset": 0, "chats": {}, "bound": False, "started_at": now(), "last_poll": None}


def _rebuild_from_inbox(state):
    st = {"offset": 0, "chats": {}, "bound": False,
          "started_at": now(), "last_poll": state.get("last_poll"),
          "outbox_offset": state.get("outbox_offset", 0)}
    for row in read_jsonl(INBOX):
        uid = row.get("update_id")
        if isinstance(uid, int):
            st["offset"] = max(st["offset"], uid + 1)
        cid = row.get("chat_id")
        if cid:
            st.setdefault("chats", {})[cfg_owner_name()] = cid
            st["bound"] = True
    try:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return st


def cfg_owner_name():
    try:
        with open(CONFIG, "r", encoding="utf-8") as f:
            return json.load(f).get("owner_name", "owner")
    except Exception:
        return "owner"


def save_state(st):
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, STATE)


def append_jsonl(path, obj):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def read_jsonl(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def api(cfg, method, payload=None, timeout=70):
    url = f"https://api.telegram.org/bot{cfg['bot_token']}/{method}"
    data = urllib.parse.urlencode(payload or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    if not body.get("ok"):
        raise RuntimeError(f"{method} failed: {body.get('description')}")
    return body.get("result")


def send_text(cfg, chat_id, text, reply_to=None):
    chunks = split_text(text)
    last = None
    for chunk in chunks:
        payload = {"chat_id": str(chat_id), "text": chunk, "disable_web_page_preview": "true"}
        if reply_to:
            payload["reply_to_message_id"] = str(reply_to)
        last = api(cfg, "sendMessage", payload)
        time.sleep(0.35)
    return last


def split_text(text, limit=3800):
    text = text.replace("\r\n", "\n")
    if len(text) <= limit:
        return [text]
    parts = []
    buf = ""
    for line in text.split("\n"):
        if len(buf) + len(line) + 1 > limit and buf:
            parts.append(buf)
            buf = line
        else:
            buf = (buf + "\n" + line) if buf else line
    if buf:
        parts.append(buf)
    return parts


def text_of(msg):
    if "text" in msg:
        return msg["text"]
    if "photo" in msg:
        return "[photo]"
    if "voice" in msg:
        return "[voice]"
    if "document" in msg:
        return "[document] " + msg["document"].get("file_name", "")
    if "audio" in msg:
        return "[audio]"
    if "video" in msg:
        return "[video]"
    if "sticker" in msg:
        return "[sticker]"
    return "[unsupported]"


def handle_command(cfg, st, chat_id, text):
    cmd, _, arg = text.partition(" ")
    cmd = cmd.split("@")[0].lower()
    if cmd == "/start":
        send_text(cfg, chat_id, (
            f"你好 {cfg['owner_name']}，我是 opencode 的 Telegram 桥接通道。\n"
            f"你在这里发的每一条消息都会被写入 {INBOX}，"
            "由 AI 在 opencode 窗口内读取并回复，回复内容会原路返回。\n"
            f"当前 chat_id = {chat_id}\n"
            "可用：/id  /ping  /status  /help"
        ))
    elif cmd == "/id":
        send_text(cfg, chat_id, f"chat_id={chat_id}\nuser_id={cfg.get('_uid')}\n会话绑定={'是' if st.get('bound') else '否'}")
    elif cmd == "/ping":
        send_text(cfg, chat_id, f"pong {now()}")
    elif cmd == "/status":
        send_text(cfg, chat_id, (
            "bridge: online\n"
            f"last_poll: {st.get('last_poll')}\n"
            f"offset: {st.get('offset')}\n"
            f"inbox: {INBOX}"
        ))
    elif cmd == "/help":
        send_text(cfg, chat_id, "直接发文字即可。AI 会在 opencode 窗口读取并回答。")
    else:
        return False
    return True


def flush_outbox(cfg, st):
    rows = read_jsonl(OUTBOX)
    cur = int(st.get("outbox_offset", 0))
    if cur > len(rows):
        cur = len(rows)
    sent = 0
    for row in rows[cur:]:
        try:
            chat_id = row.get("chat_id") or st.get("chats", {}).get(cfg["owner_name"])
            if chat_id is None:
                log("outbox entry skipped: no chat bound yet", "WARN")
                continue
            send_text(cfg, chat_id, row["text"], reply_to=row.get("reply_to"))
            append_jsonl(SENT, {"ts": now(), "chat_id": chat_id, "text": row["text"], "via": "outbox"})
            log(f"outbox delivered to {chat_id}: {row['text'][:60]!r}")
            sent += 1
        except Exception as e:
            log(f"outbox send failed: {e}", "ERROR")
            break
    st["outbox_offset"] = len(rows)
    return sent


def main():
    cfg = load_config()
    st = load_state()
    log(f"bridge starting pid={os.getpid()} bot=@{cfg['bot_username']} owner={cfg['owner_name']}")

    with open(PIDFILE, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))

    st["heartbeat"] = now()
    st["bot_username"] = cfg["bot_username"]
    save_state(st)

    try:
        info = api(cfg, "getMe", timeout=30)
        log(f"getMe ok: id={info['id']} name=@{info['username']}")
        wh = api(cfg, "getWebhookInfo", timeout=30)
        if wh.get("url"):
            log(f"webhook present ({wh['url']}), deleting so getUpdates works")
            api(cfg, "deleteWebhook", {"drop_pending_updates": "false"}, timeout=30)
    except Exception as e:
        log(f"telegram handshake failed: {e}", "ERROR")
        return 2

    if not st.get("chats"):
        st["chats"] = {}
    st["bot_username"] = cfg["bot_username"]

    backoff = 2
    while True:
        st["heartbeat"] = now()
        save_state(st)
        try:
            res = api(cfg, "getUpdates", {
                "offset": str(st.get("offset", 0)),
                "timeout": "15",
                "allowed_updates": '["message"]',
            }, timeout=40)
            st["last_poll"] = now()
            if not res:
                backoff = 2
                flush_outbox(cfg, st)
                save_state(st)
                continue
            backoff = 2
            for upd in res:
                st["offset"] = upd["update_id"] + 1
                msg = upd.get("message") or {}
                chat = msg.get("chat") or {}
                chat_id = chat.get("id")
                frm = msg.get("from") or {}
                body = text_of(msg)

                allowed = cfg.get("allowed_chat_ids") or []
                if cfg.get("bind_first_contact") and not st.get("bound") and chat.get("type") == "private":
                    st["bound"] = True
                    st["chats"][cfg["owner_name"]] = chat_id
                    log(f"bound owner chat {cfg['owner_name']} -> {chat_id}")
                if allowed and chat_id not in allowed:
                    log(f"rejected message from unauthorized chat {chat_id}", "WARN")
                    continue

                record = {
                    "ts": now(),
                    "update_id": upd["update_id"],
                    "message_id": msg.get("message_id"),
                    "chat_id": chat_id,
                    "chat_type": chat.get("type"),
                    "user": frm.get("username") or frm.get("first_name"),
                    "user_id": frm.get("id"),
                    "text": body,
                    "dispatched": False,
                }
                append_jsonl(INBOX, record)
                log(f"inbox <- chat={chat_id} user=@{record['user']} text={body[:80]!r}")

                if body.startswith("/"):
                    if handle_command(cfg, st, chat_id, body):
                        append_jsonl(SENT, {"ts": now(), "chat_id": chat_id, "text": body, "via": "builtin"})
            flush_outbox(cfg, st)
            save_state(st)
        except KeyboardInterrupt:
            log("bridge stopped by user")
            break
        except Exception as e:
            log(f"loop error: {e}", "ERROR")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)

    try:
        os.remove(PIDFILE)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())