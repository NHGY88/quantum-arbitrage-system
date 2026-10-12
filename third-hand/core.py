"""Windows Third Hand - shared core.

Config, logging, foreground-window inspection, GDI screen capture (PNG) and the
local task ledger used to talk to the opencode agent.

Pure stdlib: ctypes + zlib + json only. No third-party packages, nothing on C:.
"""

import ctypes
import ctypes.wintypes as wt
import json
import os
import struct
import time
import uuid
import zlib

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
SHOTS = os.path.join(DATA, "shots")
TASKS = os.path.join(DATA, "tasks.jsonl")
RESULTS = os.path.join(DATA, "results.jsonl")
CONFIG = os.path.join(ROOT, "config.json")
LOGDIR = os.path.join(ROOT, "logs")
LOG = os.path.join(LOGDIR, "third_hand.log")
PIDFILE = os.path.join(DATA, "third_hand.pid")

DEFAULT_CONFIG = {
    "hotkey": "ctrl+alt+space",
    "tray": True,
    "user_name": "3号小叶",
    "capture": {
        "enabled": True,
        "mode": "active_window",
        "max_files": 200,
    },
    "opencode": {
        "session_id": "auto",
        "worktree": "D:\\AI",
        "auto_dispatch": True,
        "poll_interval_ms": 1500,
        "reply_timeout_ms": 300000,
    },
    "log_level": "INFO",
}


# --------------------------------------------------------------------------- #
# config / logging / ledger
# --------------------------------------------------------------------------- #
def ensure_dirs():
    for d in (DATA, SHOTS, LOGDIR):
        os.makedirs(d, exist_ok=True)


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if os.path.exists(CONFIG):
        try:
            with open(CONFIG, "r", encoding="utf-8-sig") as f:
                user = json.load(f)
            for k, v in user.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        except Exception as e:
            log("config.json unreadable (%s), using defaults" % e, "WARN")
    return cfg


def save_config(cfg):
    ensure_dirs()
    tmp = CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG)


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def log(msg, level="INFO"):
    line = "%s [%s] %s" % (now(), level, msg)
    try:
        ensure_dirs()
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    try:
        print(line)
    except Exception:
        pass


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    return out


def append_jsonl(path, obj):
    ensure_dirs()
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


# --------------------------------------------------------------------------- #
# Win32 bindings
# --------------------------------------------------------------------------- #
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

user32.GetDC.restype = ctypes.c_void_p
user32.GetDC.argtypes = [wt.HWND]
user32.ReleaseDC.restype = ctypes.c_int
user32.ReleaseDC.argtypes = [wt.HWND, ctypes.c_void_p]
user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowTextW.argtypes = [wt.HWND, ctypes.c_wchar_p, ctypes.c_int]
user32.GetWindowTextLengthW.argtypes = [wt.HWND]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]

gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
gdi32.SelectObject.restype = ctypes.c_void_p
gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gdi32.BitBlt.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, wt.DWORD]
gdi32.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.UINT, wt.UINT,
                            ctypes.c_void_p, ctypes.c_void_p, wt.UINT]
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.DeleteDC.argtypes = [ctypes.c_void_p]

kernel32 = ctypes.windll.kernel32
kernel32.OpenProcess.restype = ctypes.c_void_p
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, wt.DWORD,
                                                ctypes.c_wchar_p, ctypes.POINTER(wt.DWORD)]
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
DWMWA_EXTENDED_FRAME_BOUNDS = 9


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
        ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


def set_dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# foreground window + capture
# --------------------------------------------------------------------------- #
def _exe_for_pid(pid):
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(h)


def _window_rect(hwnd):
    rect = wt.RECT()
    try:
        dwm = ctypes.windll.dwmapi
        if dwm.DwmGetWindowAttribute(ctypes.c_void_p(hwnd), DWMWA_EXTENDED_FRAME_BOUNDS,
                                     ctypes.byref(rect), ctypes.sizeof(rect)) == 0:
            return rect
    except Exception:
        pass
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect


def foreground_window():
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return {"hwnd": 0, "title": "", "exe": "", "pid": 0, "rect": None}
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 2)
    user32.GetWindowTextW(hwnd, buf, length + 2)
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    rect = _window_rect(hwnd)
    return {
        "hwnd": int(hwnd),
        "title": buf.value,
        "exe": _exe_for_pid(pid.value),
        "pid": int(pid.value),
        "rect": [rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top],
    }


def _png_chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def _encode_png(width, height, rgb):
    stride = width * 3
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw += rgb[y * stride:(y + 1) * stride]
    return (b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + _png_chunk(b"IEND", b""))


def screenshot_region(x, y, w, h, path):
    w = max(1, int(w))
    h = max(1, int(h))
    hdc = user32.GetDC(0)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mdc, bmp)
    gdi32.BitBlt(mdc, 0, 0, w, h, hdc, int(x), int(y), SRCCOPY)

    bi = BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = w
    bi.bmiHeader.biHeight = -h
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    bi.bmiHeader.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), DIB_RGB_COLORS)

    gdi32.SelectObject(mdc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(0, hdc)

    bgra = buf.raw
    rgb = bytearray(w * h * 3)
    for i in range(w * h):
        b = bgra[i * 4]
        g = bgra[i * 4 + 1]
        r = bgra[i * 4 + 2]
        rgb[i * 3] = r
        rgb[i * 3 + 1] = g
        rgb[i * 3 + 2] = b

    with open(path, "wb") as f:
        f.write(_encode_png(w, h, rgb))
    return path


def capture_screen(mode="active_window"):
    """Capture the foreground window (or the whole primary screen) to PNG."""
    ensure_dirs()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(SHOTS, "%s-%s.png" % (stamp, uuid.uuid4().hex[:6]))
    if mode == "active_window":
        win = foreground_window()
        rect = win.get("rect")
        if rect and rect[2] > 8 and rect[3] > 8:
            return screenshot_region(rect[0], rect[1], rect[2], rect[3], path)
    w = user32.GetSystemMetrics(0)
    h = user32.GetSystemMetrics(1)
    return screenshot_region(0, 0, w, h, path)


def prune_shots(max_files):
    try:
        files = [os.path.join(SHOTS, f) for f in os.listdir(SHOTS)]
        files = [f for f in files if os.path.isfile(f)]
        files.sort(key=os.path.getmtime, reverse=True)
        for f in files[max_files:]:
            try:
                os.remove(f)
            except Exception:
                pass
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# task ledger
# --------------------------------------------------------------------------- #
def create_task(instruction, source="local", capture=True, cfg=None):
    cfg = cfg or load_config()
    cap = cfg.get("capture", {})
    shot = None
    if capture and cap.get("enabled", True):
        try:
            shot = capture_screen(cap.get("mode", "active_window"))
            prune_shots(int(cap.get("max_files", 200)))
        except Exception as e:
            log("capture failed: %s" % e, "WARN")
    win = foreground_window() if source != "telegram" else {}
    task = {
        "id": uuid.uuid4().hex[:12],
        "ts": now(),
        "source": source,
        "user": cfg.get("user_name", "user"),
        "instruction": instruction,
        "app": {"title": win.get("title", ""), "exe": win.get("exe", ""), "pid": win.get("pid", 0)},
        "screenshot": shot,
        "dispatched": False,
    }
    append_jsonl(TASKS, task)
    log("task %s queued (app=%r)" % (task["id"], task["app"]["title"]))
    return task


def queue_task(instruction, source="hotkey", context=None, cfg=None):
    """Queue a task using an already-captured context (avoids double capture)."""
    cfg = cfg or load_config()
    ctx = context or {}
    app = ctx.get("app") or (foreground_window() if source != "telegram" else {})
    task = {
        "id": uuid.uuid4().hex[:12],
        "ts": now(),
        "source": source,
        "user": cfg.get("user_name", "user"),
        "instruction": instruction,
        "app": {"title": app.get("title", ""), "exe": app.get("exe", ""), "pid": app.get("pid", 0)},
        "screenshot": ctx.get("screenshot"),
        "dispatched": False,
    }
    append_jsonl(TASKS, task)
    log("task %s queued (app=%r)" % (task["id"], task["app"]["title"]))
    return task


def find_result(task_id):
    for row in read_jsonl(RESULTS):
        if row.get("id") == task_id:
            return row
    return None


if __name__ == "__main__":
    set_dpi_aware()
    print("foreground window:", json.dumps(foreground_window(), ensure_ascii=False))
    p = capture_screen("active_window")
    print("screenshot:", p, os.path.getsize(p), "bytes")
