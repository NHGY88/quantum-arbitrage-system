"""Windows Third Hand - command line front end.

  th.py status              show config + running state
  th.py run                 start the tray/hotkey app (background)
  th.py stop                stop the app
  th.py hotkey [combo]      show or set the global hotkey
  th.py capture             grab the focused window now
  th.py send <instruction>  queue a task and print the agent reply
  th.py tasks [n]           list recent tasks
  th.py results [n]         list recent replies
  th.py autostart [on|off]  start automatically at login (HKCU Run)
"""

import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402


def pythonw():
    cand = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if os.path.exists(cand):
        return cand
    import shutil
    return shutil.which("pythonw") or sys.executable


def pid_running():
    if not os.path.exists(core.PIDFILE):
        return None
    try:
        pid = int(open(core.PIDFILE).read().strip())
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if h:
            ctypes.windll.kernel32.CloseHandle(h)
            return pid
    except Exception:
        pass
    return None


def cmd_status(args):
    cfg = core.load_config()
    pid = pid_running()
    tasks = core.read_jsonl(core.TASKS)
    results = core.read_jsonl(core.RESULTS)
    print("app running     : %s" % (("yes, pid=%s" % pid) if pid else "no"))
    print("hotkey          : %s" % cfg.get("hotkey"))
    print("opencode bridge : auto_dispatch=%s  session=%s  worktree=%s"
          % (cfg["opencode"].get("auto_dispatch"), cfg["opencode"].get("session_id"),
             cfg["opencode"].get("worktree")))
    print("tasks queued    : %d" % len(tasks))
    print("replies stored  : %d" % len(results))
    if tasks:
        print("last task       : [%s] %s %s" % (tasks[-1]["id"], tasks[-1]["ts"],
                                                tasks[-1]["instruction"][:60]))
    if results:
        print("last reply      : [%s] %s" % (results[-1].get("id"), (results[-1].get("text") or "")[:60]))
    print("shots dir       : %s" % core.SHOTS)
    print("log             : %s" % core.LOG)


def cmd_run(args):
    if pid_running():
        print("already running (pid=%s)" % pid_running())
        return 0
    core.ensure_dirs()
    app = os.path.join(core.ROOT, "third_hand.pyw")
    DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([pythonw(), app], creationflags=DETACHED, close_fds=True)
    for _ in range(20):
        time.sleep(0.3)
        pid = pid_running()
        if pid:
            print("third_hand started pid=%s" % pid)
            return 0
    print("started (pid file not seen yet - check the log)")
    return 0


def cmd_stop(args):
    pid = pid_running()
    if not pid:
        print("not running")
        return 0
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    try:
        os.remove(core.PIDFILE)
    except Exception:
        pass
    print("stopped pid=%s" % pid)
    return 0


def cmd_hotkey(args):
    cfg = core.load_config()
    if not args:
        print(cfg.get("hotkey"))
        return 0
    import importlib.util
    spec = importlib.util.spec_from_file_location("th_app", os.path.join(core.ROOT, "third_hand.pyw"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mods, vk = mod.parse_hotkey(args[0])
    cfg["hotkey"] = args[0]
    core.save_config(cfg)
    print("hotkey set to %s (mods=0x%x vk=0x%x) - restart the app to apply" % (args[0], mods, vk))
    return 0


def cmd_capture(args):
    core.ensure_dirs()
    win = core.foreground_window()
    print("foreground: %s" % win.get("title"))
    path = core.capture_screen("active_window")
    print("saved     : %s (%d bytes)" % (path, os.path.getsize(path)))
    return 0


def cmd_send(args):
    text = " ".join(args).strip()
    if not text:
        print("usage: th.py send <instruction>")
        return 2
    task = core.create_task(text, source="cli")
    print("task [%s] queued: %s" % (task["id"], text))
    timeout = int(core.load_config()["opencode"].get("reply_timeout_ms", 300000)) / 1000.0
    deadline = time.time() + timeout
    while time.time() < deadline:
        res = core.find_result(task["id"])
        if res is not None:
            print("--- reply ---")
            print(res.get("text") or "（无文本回复）")
            return 0
        time.sleep(1.5)
    print("timeout: no reply (is OpenCode restarted so the plugin is loaded?)")
    return 1


def cmd_tasks(args):
    n = int(args[0]) if args else 15
    for row in core.read_jsonl(core.TASKS)[-n:]:
        print("[%s] %s %s | app=%r" % (row.get("id"), row.get("ts"),
                                       (row.get("instruction") or "")[:70],
                                       (row.get("app") or {}).get("title")))
    return 0


def cmd_results(args):
    n = int(args[0]) if args else 15
    for row in core.read_jsonl(core.RESULTS)[-n:]:
        print("[%s] ok=%s %s" % (row.get("id"), row.get("ok"),
                                 (row.get("text") or "").replace("\n", " ")[:100]))
    return 0


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "ThirdHand"


def cmd_autostart(args):
    import winreg
    on = (not args) or args[0].lower() in ("on", "1", "true", "yes", "enable")
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
    try:
        if on:
            val = '"%s" "%s"' % (pythonw(), os.path.join(core.ROOT, "third_hand.pyw"))
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, val)
            print("autostart ON  -> %s" % val)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
            print("autostart OFF")
    finally:
        winreg.CloseKey(key)
    return 0


CMDS = {
    "status": cmd_status, "run": cmd_run, "start": cmd_run, "stop": cmd_stop,
    "hotkey": cmd_hotkey, "capture": cmd_capture, "send": cmd_send,
    "tasks": cmd_tasks, "results": cmd_results, "autostart": cmd_autostart,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd = sys.argv[1]
    fn = CMDS.get(cmd)
    if not fn:
        print("unknown command: %s\n" % cmd)
        print(__doc__)
        return 2
    return fn(sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main() or 0)
