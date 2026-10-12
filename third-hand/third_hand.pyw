"""Windows Third Hand - tray/hotkey desktop assistant.

Global hotkey -> capture the focused app + screenshot -> type an instruction ->
opencode (with the windows-desktop / playwright MCP tools) does the work ->
the reply is shown back in the hotkey window and the tray.

Greek-free, stdlib only (ctypes + tkinter). Nothing is written outside D:\\AI.
"""

import ctypes
import ctypes.wintypes as wt
import os
import queue
import sys
import threading
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32
kernel32 = ctypes.windll.kernel32

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

VK_EXTRA = {
    "space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B,
    "backspace": 0x08, "delete": 0x2E, "insert": 0x2D,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD,
    "\\": 0xDC, ";": 0xBA, "'": 0xDE, ",": 0xBC, ".": 0xBE, "/": 0xBF,
}


def parse_hotkey(text):
    mods = MOD_NOREPEAT
    vk = None
    for part in [p.strip().lower() for p in str(text).split("+") if p.strip()]:
        if part in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif part == "alt":
            mods |= MOD_ALT
        elif part == "shift":
            mods |= MOD_SHIFT
        elif part in ("win", "super", "meta"):
            mods |= MOD_WIN
        elif len(part) == 1 and part.isalpha():
            vk = ord(part.upper())
        elif len(part) == 1 and part.isdigit():
            vk = ord(part)
        elif len(part) >= 2 and part[0] == "f" and part[1:].isdigit():
            vk = 0x70 + int(part[1:]) - 1
        elif part in VK_EXTRA:
            vk = VK_EXTRA[part]
    if vk is None:
        vk = VK_EXTRA["space"]
    if not (mods & (MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_WIN)):
        mods |= MOD_CONTROL | MOD_ALT
    return mods, vk


# --------------------------------------------------------------------------- #
# global hotkey
# --------------------------------------------------------------------------- #
def hotkey_loop(mods, vk, evq, hotkey_id=0x7A11):
    if not user32.RegisterHotKey(None, hotkey_id, mods, vk):
        core.log("RegisterHotKey failed for current hotkey (already taken?) - "
                 "change 'hotkey' in config.json and restart", "ERROR")
        return
    core.log("global hotkey registered")
    msg = wt.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == WM_HOTKEY:
            evq.put(("hotkey",))
    user32.UnregisterHotKey(None, hotkey_id)


# --------------------------------------------------------------------------- #
# tray icon
# --------------------------------------------------------------------------- #
WM_TRAYICON = 0x8000 + 1
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 1, 2, 4
MIIM_ID = 2


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uID", wt.UINT), ("uFlags", wt.UINT),
        ("uCallbackMessage", wt.UINT), ("hIcon", wt.HANDLE),
        ("szTip", ctypes.c_wchar * 128),
        ("dwState", wt.DWORD), ("dwStateMask", wt.DWORD),
        ("szInfo", ctypes.c_wchar * 256), ("uTimeoutOrVersion", wt.UINT),
        ("szInfoTitle", ctypes.c_wchar * 64), ("dwInfoFlags", wt.DWORD),
        ("guidItem", GUID), ("hBalloonIcon", wt.HANDLE),
    ]


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HANDLE), ("hIcon", wt.HANDLE),
        ("hCursor", wt.HANDLE), ("hbrBackground", wt.HANDLE),
        ("lpszMenuName", ctypes.c_wchar_p), ("lpszClassName", ctypes.c_wchar_p),
    ]


# 64-bit Win32 prototypes (default ctypes guesses are 32-bit and truncate handles)
user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
user32.RegisterHotKey.restype = wt.BOOL
user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wt.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.GetMessageW.restype = wt.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wt.ATOM
user32.CreateWindowExW.argtypes = [wt.DWORD, ctypes.c_wchar_p, ctypes.c_wchar_p, wt.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wt.HWND, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
user32.CreateWindowExW.restype = wt.HWND
user32.CreatePopupMenu.restype = ctypes.c_void_p
user32.AppendMenuW.argtypes = [ctypes.c_void_p, wt.UINT, ctypes.c_size_t, ctypes.c_wchar_p]
user32.TrackPopupMenu.argtypes = [ctypes.c_void_p, wt.UINT, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, wt.HWND, ctypes.c_void_p]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.DestroyMenu.argtypes = [ctypes.c_void_p]
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.LoadIconW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.LoadIconW.restype = ctypes.c_void_p
shell32.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
shell32.Shell_NotifyIconW.restype = wt.BOOL
kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
kernel32.GetModuleHandleW.restype = ctypes.c_void_p


class Tray:
    def __init__(self, on_new, on_shots, on_logs, on_quit, tip="Third Hand"):
        self.on_new = on_new
        self.on_shots = on_shots
        self.on_logs = on_logs
        self.on_quit = on_quit
        self.tip = tip
        self.hwnd = None
        self._proc = None
        self.class_name = "ThirdHandTrayClass"

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAYICON:
            if lparam == 0x0202:  # WM_LBUTTONUP
                self.on_new()
            elif lparam == 0x0205:  # WM_RBUTTONUP
                self._menu()
            return 0
        if msg == 0x0002:  # WM_DESTROY
            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = hwnd
            nid.uID = 1
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _menu(self):
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, 0x0000, 1, "新建任务 (Ctrl+Alt+Space)")
        user32.AppendMenuW(menu, 0x0000, 2, "打开截图目录")
        user32.AppendMenuW(menu, 0x0000, 3, "打开日志")
        user32.AppendMenuW(menu, 0x0800, 0, None)
        user32.AppendMenuW(menu, 0x0000, 9, "退出")
        pt = wt.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(self.hwnd)
        cmd = user32.TrackPopupMenu(menu, 0x0100 | 0x0002, pt.x, pt.y, 0, self.hwnd, None)
        user32.DestroyMenu(menu)
        if cmd == 1:
            self.on_new()
        elif cmd == 2:
            self.on_shots()
        elif cmd == 3:
            self.on_logs()
        elif cmd == 9:
            self.on_quit()

    def run(self):
        self._proc = WNDPROC(self._wndproc)
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._proc
        wc.hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)
        wc.lpszClassName = self.class_name
        user32.RegisterClassW(ctypes.byref(wc))
        self.hwnd = user32.CreateWindowExW(0, self.class_name, "Third Hand", 0,
                                           0, 0, 0, 0, None, None, wc.hInstance, None)
        if not self.hwnd:
            raise RuntimeError("CreateWindowEx failed")
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = user32.LoadIconW(None, 32512)  # IDI_APPLICATION
        nid.szTip = self.tip
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
        core.log("tray icon added")
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #
class App:
    def __init__(self, root, cfg, evq, seed=None):
        self.root = root
        self.cfg = cfg
        self.evq = evq
        self.win = None
        self.entry = None
        self.txt = None
        self.status = None
        self.context = {}
        self.task_id = None
        self.last_foreign = seed or None
        root.withdraw()
        root.after(120, self._pump)
        root.after(500, self._watch_foreground)

    def _watch_foreground(self):
        try:
            fg = core.foreground_window()
            if fg.get("pid") and fg.get("pid") != os.getpid() and fg.get("title"):
                if not self.last_foreign or self.last_foreign.get("title") != fg.get("title"):
                    core.log("tracked foreground app=%r pid=%s" % (fg.get("title"), fg.get("pid")))
                self.last_foreign = fg
        except Exception:
            pass
        self.root.after(700, self._watch_foreground)

    def _pump(self):
        try:
            while True:
                ev = self.evq.get_nowait()
                self._handle(ev)
        except queue.Empty:
            pass
        self.root.after(120, self._pump)

    def _handle(self, ev):
        kind = ev[0]
        if kind in ("hotkey", "new"):
            core.log("hotkey/trigger -> opening prompt")
            self.open_prompt()
        elif kind == "shots":
            try:
                os.startfile(core.SHOTS)
            except Exception as e:
                core.log("open shots failed: %s" % e, "WARN")
        elif kind == "logs":
            try:
                os.startfile(core.LOG)
            except Exception as e:
                core.log("open log failed: %s" % e, "WARN")
        elif kind == "quit":
            self.root.quit()

    def open_prompt(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()
            if self.entry.winfo_exists():
                self.entry.focus_set()
            return

        fg = core.foreground_window()
        if not fg.get("title") or fg.get("pid") == os.getpid():
            fg = self.last_foreign or fg
        shot = None
        cap = self.cfg.get("capture", {})
        if cap.get("enabled", True):
            try:
                shot = core.capture_screen(cap.get("mode", "active_window"))
                core.prune_shots(int(cap.get("max_files", 200)))
            except Exception as e:
                core.log("capture failed: %s" % e, "WARN")
        self.context = {"app": fg, "screenshot": shot}
        core.log("prompt for app=%r pid=%s (self=%s) shot=%s"
                 % (fg.get("title"), fg.get("pid"), os.getpid(), shot))

        win = tk.Toplevel(self.root)
        self.win = win
        win.title("Third Hand")
        win.attributes("-topmost", True)
        win.resizable(False, False)

        frm = tk.Frame(win, padx=14, pady=12)
        frm.pack(fill="both", expand=True)

        app_title = fg.get("title") or "(无标题窗口)"
        tk.Label(frm, text="Third Hand  ·  @" + app_title[:70],
                 font=("Segoe UI", 10, "bold"), anchor="w", justify="left").pack(fill="x")

        tk.Label(frm, text="指令（Enter 执行 · Esc 取消 · Shift+Enter 换行）",
                 fg="#666", font=("Segoe UI", 8), anchor="w").pack(fill="x", pady=(2, 6))

        self.entry = tk.Text(frm, width=64, height=3, font=("Segoe UI", 10),
                             wrap="word", undo=True)
        self.entry.pack(fill="x")
        self.entry.focus_set()
        self.entry.bind("<Return>", self._on_return)
        self.entry.bind("<Escape>", lambda e: self.close())

        self.txt = tk.Text(frm, width=64, height=10, font=("Consolas", 9),
                           wrap="word", fg="#0b5")
        self.txt.configure(state="disabled")

        self.status = tk.Label(frm, text="就绪", fg="#2a7", anchor="w",
                               font=("Segoe UI", 9))
        self.status.pack(fill="x", pady=(6, 2))

        bar = tk.Frame(frm)
        bar.pack(fill="x", pady=(4, 0))
        tk.Button(bar, text="执行", width=8, command=self.submit).pack(side="left")
        tk.Button(bar, text="复制回复", width=10, command=self.copy_reply).pack(side="left", padx=(6, 0))
        tk.Button(bar, text="截图目录", width=10,
                  command=lambda: os.startfile(core.SHOTS)).pack(side="left", padx=(6, 0))
        tk.Button(bar, text="关闭", width=8, command=self.close).pack(side="right")

        win.protocol("WM_DELETE_WINDOW", self.close)
        win.bind("<Escape>", lambda e: self.close())
        self._center(win, 600, 240)
        win.lift()
        win.focus_force()
        win.after(80, self._focus_entry)

    def _focus_entry(self):
        try:
            if self.win and self.win.winfo_exists():
                self.win.focus_force()
                self.entry.focus_set()
        except Exception:
            pass

    def _center(self, win, w, h):
        win.update_idletasks()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = (sw - w) // 2
        y = max(60, sh // 4)
        win.geometry("%dx%d+%d+%d" % (w, h, x, y))

    def _on_return(self, event):
        if event.state & 0x0001:  # Shift held -> newline
            return
        self.submit()
        return "break"

    def submit(self):
        text = self.entry.get("1.0", "end").strip()
        if not text:
            return
        if text.startswith("@"):
            pass  # @app target is parsed by the agent
        try:
            task = core.queue_task(text, source="hotkey", context=self.context, cfg=self.cfg)
        except Exception as e:
            self.set_status("提交失败：%s" % e, "#c33")
            return
        self.task_id = task["id"]
        self.entry.configure(state="disabled")
        self.set_status("已提交 [%s]，交给 opencode 处理中…" % task["id"], "#e70")
        self._poll_result(deadline=_now_ms() + int(self.cfg["opencode"].get("reply_timeout_ms", 300000)))

    def _poll_result(self, deadline):
        if self.win is None or not self.win.winfo_exists():
            return
        res = core.find_result(self.task_id)
        if res is not None:
            ok = res.get("ok", True)
            body = res.get("text") or "（无文本回复）"
            if res.get("error"):
                body = "%s\n\n错误：%s" % (body, res["error"])
            self.show_reply(body, ok)
            return
        if _now_ms() > deadline:
            self.set_status("opencode 未在超时时间内返回。"
                            "若插件尚未加载，请重启 OpenCode。", "#c33")
            return
        self.win.after(1500, lambda: self._poll_result(deadline))

    def show_reply(self, text, ok=True):
        self.set_status("完成 [%s]" % self.task_id, "#2a7" if ok else "#c33")
        try:
            self.txt.pack(fill="both", expand=True, pady=(8, 0))
            self.txt.configure(state="normal", fg="#0b5" if ok else "#c33")
            self.txt.delete("1.0", "end")
            self.txt.insert("1.0", text)
            self.txt.configure(state="disabled")
            self.win.geometry("640x420")
            self.win.lift()
        except Exception:
            pass

    def copy_reply(self):
        try:
            if self.txt is None:
                return
            data = self.txt.get("1.0", "end").strip()
            self.root.clipboard_clear()
            self.root.clipboard_append(data)
            self.set_status("已复制到剪贴板", "#2a7")
        except Exception:
            pass

    def set_status(self, text, color="#666"):
        try:
            self.status.configure(text=text, fg=color)
        except Exception:
            pass

    def close(self):
        try:
            self.win.destroy()
        except Exception:
            pass
        self.win = None


def _now_ms():
    import time
    return int(time.time() * 1000)


def main():
    core.ensure_dirs()
    core.set_dpi_aware()
    cfg = core.load_config()

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.CreateMutexW.restype = ctypes.c_void_p
    _k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    hm = _k32.CreateMutexW(None, 0, "Local\\third_hand_v1")
    if not hm:
        core.log("mutex create failed, exiting", "WARN")
        return
    if ctypes.get_last_error() == 183:
        core.log("already running, exiting", "WARN")
        return
    with open(core.PIDFILE, "w") as f:
        f.write(str(os.getpid()))

    mods, vk = parse_hotkey(cfg.get("hotkey", "ctrl+alt+space"))
    evq = queue.Queue()

    seed = None
    try:
        seed = core.foreground_window()
        if seed.get("pid") == os.getpid() or not seed.get("title"):
            seed = None
    except Exception:
        seed = None

    threading.Thread(target=hotkey_loop, args=(mods, vk, evq), daemon=True).start()

    if cfg.get("tray", True):
        try:
            tray = Tray(on_new=lambda: evq.put(("new",)),
                        on_shots=lambda: evq.put(("shots",)),
                        on_logs=lambda: evq.put(("logs",)),
                        on_quit=lambda: evq.put(("quit",)))
            threading.Thread(target=tray.run, daemon=True).start()
        except Exception as e:
            core.log("tray init failed: %s" % e, "WARN")

    root = tk.Tk()
    root.title("Third Hand")
    App(root, cfg, evq, seed=seed)
    core.log("third_hand started pid=%s hotkey=%s" % (os.getpid(), cfg.get("hotkey")))
    try:
        root.mainloop()
    finally:
        try:
            os.remove(core.PIDFILE)
        except Exception:
            pass
        core.log("third_hand stopped")


if __name__ == "__main__":
    main()
