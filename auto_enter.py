# -*- coding: utf-8 -*-
"""
AutoEnterScheduler - 定时回车工具 v1.2.0

功能：
    1. 枚举系统中所有可见顶层窗口，支持多选（Ctrl/Shift）。
    2. 设定"触发时间"(每天 X 点 Y 分) 与 "重复间隔/总次数"。
    3. 到点后向目标窗口发送回车(Enter)键。支持两种发键模式：
         - 前台注入 (keybd_event)：切到前台后用真实键盘事件，发完恢复原前台。
           适用于 Windows Terminal / Claude / 浏览器 / Electron 等。
         - 后台投递 (PostMessage)：不打扰前台，仅对普通 Win32 输入框有效。
    4. 配置自动保存/加载，记住窗口选择和设置。
    5. 倒计时显示，实时知道距离下次触发还有多久。
    6. 日志同时写入文件，方便排查问题。
    7. 窗口标题自动刷新（每 30 秒）。
    8. 立即执行一次（不改变定时计划）。

适用场景：AI 额度每 5 小时刷新，凌晨 5 点自动触发，避免手动守候。

作者：Thatgfsj
"""

import ctypes
from ctypes import wintypes
import threading
import time
import datetime
import queue
import sys
import os
import json

import tkinter as tk
from tkinter import ttk, messagebox

# --------------------------- 常量 ---------------------------
CONFIG_FILE = "config.json"
LOG_FILE = "log.txt"
VERSION = "1.2.0"

# --------------------------- Win32 声明 ---------------------------
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
VK_RETURN = 0x0D
GW_OWNER = 4
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
SW_RESTORE = 9
SW_SHOW = 5

# 64位安全：设定 argtypes/restype
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.GetWindowLongW.argtypes = [wintypes.HWND, wintypes.INT]; user32.GetWindowLongW.restype = wintypes.LONG
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, wintypes.INT]; user32.GetWindowTextW.restype = wintypes.INT
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]; user32.GetWindowTextLengthW.restype = wintypes.INT
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, wintypes.INT]; user32.GetClassNameW.restype = wintypes.INT
user32.IsWindowVisible.argtypes = [wintypes.HWND]; user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]; user32.IsWindow.restype = wintypes.BOOL
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]; user32.GetWindow.restype = wintypes.HWND
user32.GetForegroundWindow.argtypes = []; user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]; user32.SetForegroundWindow.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]; user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.ShowWindow.argtypes = [wintypes.HWND, wintypes.INT]; user32.ShowWindow.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = [wintypes.HWND]; user32.BringWindowToTop.restype = wintypes.BOOL
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]; user32.AttachThreadInput.restype = wintypes.BOOL
user32.GetFocus.argtypes = []; user32.GetFocus.restype = wintypes.HWND
user32.SetFocus.argtypes = [wintypes.HWND]; user32.SetFocus.restype = wintypes.HWND
user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_void_p]
user32.keybd_event.restype = None


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_void_p)]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT

# 窗口枚举
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
_enum_proc_type = EnumWindowsProc
kernel32.GetLastError.argtypes = []
kernel32.GetLastError.restype = wintypes.DWORD


# --------------------------- 日志 ---------------------------
_log_file = None


def _init_log():
    global _log_file
    try:
        _log_file = open(LOG_FILE, "a", encoding="utf-8")
        _log_file.write(f"\n{'='*60}\n")
        _log_file.write(f"启动时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        _log_file.write(f"{'='*60}\n")
    except Exception:
        _log_file = None


def _log_to_file(msg):
    if _log_file:
        try:
            _log_file.write(msg + "\n")
            _log_file.flush()
        except Exception:
            pass


# --------------------------- 配置 ---------------------------
def load_config():
    """加载配置文件，返回 dict。"""
    default = {
        "time": "05:00",
        "count": 1,
        "interval": 0.5,
        "win_gap": 1.5,
        "mode": "auto",
        "restore": True,
        "filter": "",
        "selected_hwnds": [],  # 保存选中的窗口句柄
    }
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # 合并默认值
            for k, v in default.items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
    except Exception:
        pass
    return default


def save_config(cfg):
    """保存配置到文件。"""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# --------------------------- 窗口枚举 ---------------------------
def _is_real_window(hwnd):
    if not user32.IsWindowVisible(hwnd):
        return False
    if user32.GetWindowTextLengthW(hwnd) == 0:
        return False
    owner = user32.GetWindow(hwnd, GW_OWNER)
    if owner:
        return False
    return True


def enum_windows():
    results = []

    @_enum_proc_type
    def _cb(hwnd, _lparam):
        if _is_real_window(hwnd):
            n = user32.GetWindowTextLengthW(hwnd) + 1
            buf = ctypes.create_unicode_buffer(n)
            user32.GetWindowTextW(hwnd, buf, n)
            if buf.value:
                results.append((hwnd, buf.value))
        return 1

    cb_ref = _cb
    user32.EnumWindows(cb_ref, 0)
    return results


def _class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def needs_foreground(hwnd):
    """判断该窗口是否需要前台注入。"""
    cls = _class_name(hwnd).lower()
    return any(kw in cls for kw in [
        "cascadia", "chromium", "chrome_widgetwin", "winuiedit",
        "modern", "desktopwindowcontentbridge", "inputsite"
    ])


# --------------------------- 发键 ---------------------------
def send_enter_postmessage(hwnd, count=1, interval=0.2):
    """后台 PostMessage 模式。"""
    for i in range(count):
        user32.PostMessageW(hwnd, WM_KEYDOWN, VK_RETURN, 0)
        user32.PostMessageW(hwnd, WM_CHAR, VK_RETURN, 0)
        user32.PostMessageW(hwnd, WM_KEYUP, VK_RETURN, 0)
        if count > 1 and i < count - 1:
            time.sleep(interval)


def _force_foreground(hwnd):
    """强制把 hwnd 切到前台，返回 (prev_fg, attached_tids)。"""
    prev_fg = user32.GetForegroundWindow()
    if prev_fg == hwnd:
        return prev_fg, []

    cur_tid = kernel32.GetCurrentThreadId()
    target_tid = user32.GetWindowThreadProcessId(hwnd, None)

    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.BringWindowToTop(hwnd)

    # Alt 键解锁前台锁
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 0x0002, 0)

    # AttachThreadInput 挂钩
    attached = []
    for tid in {target_tid,
                user32.GetWindowThreadProcessId(prev_fg, None) if prev_fg else 0}:
        if tid and tid != cur_tid:
            if user32.AttachThreadInput(tid, cur_tid, True):
                attached.append(tid)

    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    user32.SetFocus(hwnd)

    # 等待焦点切换
    for _ in range(20):
        if user32.GetForegroundWindow() == hwnd:
            break
        time.sleep(0.025)
    time.sleep(0.1)
    return prev_fg, attached


def _detach_threads(attached):
    """解除 AttachThreadInput 挂钩。"""
    cur_tid = kernel32.GetCurrentThreadId()
    for tid in attached:
        user32.AttachThreadInput(tid, cur_tid, False)


def send_enter_sendinput(hwnd, count=1, interval=0.2, restore=True):
    """前台 keybd_event 模式。"""
    prev_fg, attached = _force_foreground(hwnd)
    try:
        if user32.GetForegroundWindow() != hwnd:
            raise OSError(f"无法将窗口切到前台(当前前台={user32.GetForegroundWindow()})")

        used = "keybd_event"
        for i in range(count):
            user32.keybd_event(VK_RETURN, 0, 0, 0)
            user32.keybd_event(VK_RETURN, 0, 0x0002, 0)
            if count > 1 and i < count - 1:
                time.sleep(interval)
    finally:
        _detach_threads(attached)
        if restore and prev_fg and user32.IsWindow(prev_fg):
            time.sleep(0.1)
            _, restore_attached = _force_foreground(prev_fg)
            _detach_threads(restore_attached)
    return used


def send_enter(hwnd, count=1, interval=0.2, mode="auto", restore=True):
    """统一入口。"""
    if mode == "bg":
        send_enter_postmessage(hwnd, count, interval)
        return "PostMessage"
    if mode == "fg" or (mode == "auto" and needs_foreground(hwnd)):
        used = send_enter_sendinput(hwnd, count, interval, restore=restore)
        return f"前台 {used}"
    send_enter_postmessage(hwnd, count, interval)
    return "PostMessage"


# --------------------------- 调度线程 ---------------------------
class SchedulerThread(threading.Thread):
    def __init__(self, targets, target_time_str, repeat_count, repeat_interval,
                 win_gap, mode, restore, log_q, stop_evt, next_trigger_var=None):
        """
        targets: [(hwnd, title), ...]
        next_trigger_var: tkinter StringVar，用于在 GUI 显示下次触发时间
        """
        super().__init__(daemon=True)
        self.targets = targets
        self.target_time_str = target_time_str
        self.repeat_count = max(1, int(repeat_count))
        self.repeat_interval = max(0.1, float(repeat_interval))
        self.win_gap = max(0.2, float(win_gap))
        self.mode = mode
        self.restore = restore
        self.log_q = log_q
        self.stop_evt = stop_evt
        self.next_trigger_var = next_trigger_var

    def _log(self, msg):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        self.log_q.put(line)
        _log_to_file(line)

    def _sleep_interruptible(self, seconds):
        steps = max(1, int(seconds / 0.2))
        for _ in range(steps):
            if self.stop_evt.is_set():
                return True
            time.sleep(seconds / steps)
        return False

    def run(self):
        try:
            hh, mm = [int(x) for x in self.target_time_str.split(":")]
        except Exception:
            self._log(f"时间格式错误: {self.target_time_str}")
            return

        now = datetime.datetime.now()
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)

        wait_seconds = (target - now).total_seconds()
        self._log(f"已启动。目标窗口 {len(self.targets)} 个，发键模式: {self.mode}，恢复前台: {self.restore}")
        for i, (h, t) in enumerate(self.targets, 1):
            self._log(f"  目标{i}: [{h}] {t}")
        self._log(f"下次触发: {target.strftime('%Y-%m-%d %H:%M:%S')} (约 {wait_seconds/3600:.2f} 小时后)")

        # 更新 GUI 的下次触发时间
        if self.next_trigger_var:
            self.next_trigger_var.set(target.strftime('%Y-%m-%d %H:%M:%S'))

        # 等待到触发时刻，每秒更新倒计时
        while not self.stop_evt.is_set():
            remaining = (target - datetime.datetime.now()).total_seconds()
            if remaining <= 0:
                break
            # 更新状态栏倒计时
            hours = int(remaining // 3600)
            mins = int((remaining % 3600) // 60)
            secs = int(remaining % 60)
            if self.next_trigger_var:
                self.next_trigger_var.set(f"{target.strftime('%H:%M')} (还剩 {hours}时{mins}分{secs}秒)")
            time.sleep(min(1.0, remaining))

        if self.stop_evt.is_set():
            self._log("已停止(等待期间)。")
            if self.next_trigger_var:
                self.next_trigger_var.set("已停止")
            return

        # 过滤已关闭的窗口
        alive = [(h, t) for h, t in self.targets if user32.IsWindow(h)]
        closed = [(h, t) for h, t in self.targets if not user32.IsWindow(h)]
        for h, t in closed:
            self._log(f"跳过(已关闭): [{h}] {t}")
        if not alive:
            self._log("错误: 所有目标窗口都已关闭，无法发送。")
            return

        self._log(f"=== 到点触发，向 {len(alive)} 个窗口各发 {self.repeat_count} 次回车 ===")
        for idx, (hwnd, title) in enumerate(alive):
            if self.stop_evt.is_set():
                self._log("已停止(发送期间)。")
                return
            label = title if len(title) <= 30 else title[:28] + "…"
            self._log(f"— 窗口{idx+1}/{len(alive)}: [{hwnd}] {label}")
            for i in range(self.repeat_count):
                if self.stop_evt.is_set():
                    self._log("已停止(发送期间)。")
                    return
                try:
                    used = send_enter(hwnd, 1, mode=self.mode, restore=self.restore)
                    self._log(f"    第 {i+1}/{self.repeat_count} 次 ✓ ({used})")
                except Exception as e:
                    self._log(f"    第 {i+1}/{self.repeat_count} 次 ✗ {e}")
                if i < self.repeat_count - 1:
                    if self._sleep_interruptible(self.repeat_interval):
                        return
            if idx < len(alive) - 1:
                if self._sleep_interruptible(self.win_gap):
                    return

        self._log("=== 全部发送完毕 ===")
        if not self.stop_evt.is_set():
            self._log("已自动安排明天同一时刻再次触发。")
            if self.next_trigger_var:
                # 计算明天同一时刻
                tomorrow = target + datetime.timedelta(days=1)
                self.next_trigger_var.set(tomorrow.strftime('%Y-%m-%d %H:%M:%S') + " (明天)")


# --------------------------- GUI ---------------------------
MODE_DESC = {
    "auto": "自动判断（推荐）",
    "fg": "强制前台 keybd_event",
    "bg": "后台 PostMessage",
}


class App:
    def __init__(self, root):
        self.root = root
        self._selected = []  # [(hwnd, title), ...]
        self.scheduler = None
        self.stop_evt = None
        self.log_q = queue.Queue()
        self._log_lines = []  # 保存日志行用于文件写入
        self._countdown_id = None

        root.title(f"定时回车工具 v{VERSION}")
        root.geometry("660x750")
        root.minsize(600, 680)

        try:
            ico = resource_path("icon.ico")
            if os.path.exists(ico):
                root.iconbitmap(default=ico)
        except Exception:
            pass

        # 加载配置
        self._config = load_config()

        # 初始化日志文件
        _init_log()

        self._build_ui()
        self._load_config_to_ui()
        self._poll_log()
        self._start_auto_refresh()

        # 关闭时保存配置
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        # ① 目标窗口
        frm_win = ttk.LabelFrame(self.root, text="① 选择目标窗口（可多选：Ctrl/Shift 连选，Ctrl+A 全选）")
        frm_win.pack(fill="x", **pad)

        top = ttk.Frame(frm_win); top.pack(fill="x", padx=8, pady=6)
        ttk.Button(top, text="刷新窗口列表", command=self.refresh_windows).pack(side="left")
        ttk.Label(top, text="   过滤:").pack(side="left")
        self.filter_var = tk.StringVar()
        ent = ttk.Entry(top, textvariable=self.filter_var, width=20); ent.pack(side="left", padx=4)
        ent.bind("<Return>", lambda e: self.refresh_windows())
        ttk.Button(top, text="按此过滤", command=self.refresh_windows).pack(side="left")
        ttk.Button(top, text="全选", command=self.select_all).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="清空选择", command=self.clear_selection).pack(side="left", padx=4)

        list_frm = ttk.Frame(frm_win); list_frm.pack(fill="both", expand=True, padx=8, pady=(0, 6))
        self.win_list = tk.Listbox(list_frm, height=9, activestyle="dotbox",
            selectmode="extended")
        sb = ttk.Scrollbar(list_frm, orient="vertical", command=self.win_list.yview)
        self.win_list.configure(yscrollcommand=sb.set)
        self.win_list.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        self.win_list.bind("<<ListboxSelect>>", self.on_select_window)
        self.win_list.bind("<Control-a>", lambda e: (self.select_all(), "break")[1])
        self._listbox_has_focus = False
        self.win_list.bind("<FocusIn>", lambda e: setattr(self, '_listbox_has_focus', True))
        self.win_list.bind("<FocusOut>", lambda e: setattr(self, '_listbox_has_focus', False))
        self._windows = []

        sel_frm = ttk.Frame(frm_win); sel_frm.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Label(sel_frm, text="已选目标:").pack(side="left")
        self.selected_var = tk.StringVar(value="0 个")
        ttk.Label(sel_frm, textvariable=self.selected_var, foreground="blue").pack(side="left")
        ttk.Label(sel_frm, text="  (到点会依次向这些窗口发回车)").pack(side="left")

        # ② 时间设置
        frm_time = ttk.LabelFrame(self.root, text="② 触发时间与重复次数")
        frm_time.pack(fill="x", **pad)
        r1 = ttk.Frame(frm_time); r1.pack(fill="x", padx=8, pady=6)
        ttk.Label(r1, text="每天触发时刻 (HH:MM):").pack(side="left")
        self.time_var = tk.StringVar(value="05:00")
        ttk.Entry(r1, textvariable=self.time_var, width=8).pack(side="left", padx=6)
        ttk.Label(r1, text="   例如 05:00 = 凌晨5点").pack(side="left")
        r2 = ttk.Frame(frm_time); r2.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(r2, text="到点后发送次数:").pack(side="left")
        self.count_var = tk.StringVar(value="1")
        ttk.Entry(r2, textvariable=self.count_var, width=6).pack(side="left", padx=6)
        ttk.Label(r2, text="   间隔(秒):").pack(side="left")
        self.interval_var = tk.StringVar(value="0.5")
        ttk.Entry(r2, textvariable=self.interval_var, width=6).pack(side="left", padx=6)
        r3 = ttk.Frame(frm_time); r3.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(r3, text="多窗口切换间隔(秒):").pack(side="left")
        self.win_gap_var = tk.StringVar(value="1.5")
        ttk.Entry(r3, textvariable=self.win_gap_var, width=6).pack(side="left", padx=6)
        ttk.Label(r3, text="   多开时避免前台打架", foreground="#666").pack(side="left")

        # ③ 发键模式
        frm_mode = ttk.LabelFrame(self.root, text="③ 发键模式")
        frm_mode.pack(fill="x", **pad)
        m1 = ttk.Frame(frm_mode); m1.pack(fill="x", padx=8, pady=6)
        ttk.Label(m1, text="模式:").pack(side="left")
        self.mode_var = tk.StringVar(value="auto")
        for v in ("auto", "fg", "bg"):
            ttk.Radiobutton(m1, text=MODE_DESC[v], variable=self.mode_var, value=v).pack(side="left", padx=6)
        m2 = ttk.Frame(frm_mode); m2.pack(fill="x", padx=8, pady=(0, 6))
        self.restore_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(m2, text="发完后恢复我原来的前台窗口（推荐）",
                        variable=self.restore_var).pack(side="left")

        # ④ 控制按钮 + 状态
        frm_ctrl = ttk.LabelFrame(self.root, text="④ 控制")
        frm_ctrl.pack(fill="x", **pad)
        btn_row = ttk.Frame(frm_ctrl); btn_row.pack(fill="x", padx=8, pady=6)
        self.btn_start = ttk.Button(btn_row, text="▶ 启动定时", command=self.start)
        self.btn_start.pack(side="left", padx=4)
        self.btn_stop = ttk.Button(btn_row, text="■ 停止", command=self.stop, state="disabled")
        self.btn_stop.pack(side="left", padx=4)
        self.btn_test = ttk.Button(btn_row, text="立即测试一次", command=self.test_send)
        self.btn_test.pack(side="left", padx=4)
        self.btn_now = ttk.Button(btn_row, text="立即执行一次（不影响定时）", command=self.execute_now)
        self.btn_now.pack(side="left", padx=4)

        # 状态行
        status_row = ttk.Frame(frm_ctrl); status_row.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Label(status_row, text="状态:").pack(side="left")
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(status_row, textvariable=self.status_var, foreground="#333").pack(side="left", padx=4)
        ttk.Label(status_row, text="   下次触发:").pack(side="left")
        self.next_trigger_var = tk.StringVar(value="-")
        ttk.Label(status_row, textvariable=self.next_trigger_var, foreground="#0066cc").pack(side="left", padx=4)

        # ⑤ 日志
        frm_log = ttk.LabelFrame(self.root, text="⑤ 日志（同时保存到 log.txt）")
        frm_log.pack(fill="both", expand=True, **pad)
        li = ttk.Frame(frm_log); li.pack(fill="both", expand=True, padx=8, pady=8)
        self.log_text = tk.Text(li, height=10, wrap="word", state="disabled")
        sb2 = ttk.Scrollbar(li, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb2.set)
        self.log_text.pack(side="left", fill="both", expand=True); sb2.pack(side="right", fill="y")

        # 底部状态栏
        self.bottom_status = tk.StringVar(value="就绪。请选择窗口、设置时间、测试后启动。")
        ttk.Label(self.root, textvariable=self.bottom_status, relief="sunken", anchor="w").pack(fill="x", side="bottom")

        self.refresh_windows()

    # ---- 配置加载/保存 ----
    def _load_config_to_ui(self):
        cfg = self._config
        self.time_var.set(cfg.get("time", "05:00"))
        self.count_var.set(str(cfg.get("count", 1)))
        self.interval_var.set(str(cfg.get("interval", 0.5)))
        self.win_gap_var.set(str(cfg.get("win_gap", 1.5)))
        self.mode_var.set(cfg.get("mode", "auto"))
        self.restore_var.set(cfg.get("restore", True))
        self.filter_var.set(cfg.get("filter", ""))

        # 尝试恢复选中的窗口（按 hwnd 匹配）
        saved_hwnds = set(cfg.get("selected_hwnds", []))
        if saved_hwnds:
            self.refresh_windows()
            for i, (hwnd, _) in enumerate(self._windows):
                if hwnd in saved_hwnds:
                    self.win_list.select_set(i)
            self._update_selection()

    def _save_config_from_ui(self):
        cfg = {
            "time": self.time_var.get(),
            "count": int(self.count_var.get()) if self.count_var.get().isdigit() else 1,
            "interval": float(self.interval_var.get()) if self.interval_var.get() else 0.5,
            "win_gap": float(self.win_gap_var.get()) if self.win_gap_var.get() else 1.5,
            "mode": self.mode_var.get(),
            "restore": self.restore_var.get(),
            "filter": self.filter_var.get(),
            "selected_hwnds": [h for h, _ in self._selected],
        }
        save_config(cfg)

    def _on_close(self):
        self._save_config_from_ui()
        if self.stop_evt:
            self.stop_evt.set()
        self.root.destroy()

    # ---- 窗口列表 ----
    def refresh_windows(self):
        self.win_list.delete(0, "end")
        self._windows = []
        kw = self.filter_var.get().strip().lower()
        for hwnd, title in enum_windows():
            if kw and kw not in title.lower():
                continue
            self._windows.append((hwnd, title))
            mark = " [需前台]" if needs_foreground(hwnd) else ""
            self.win_list.insert("end", f"[{hwnd}]{mark} {title}")
        self.bottom_status.set(f"已列出 {len(self._windows)} 个窗口")

    def _start_auto_refresh(self):
        """每 30 秒自动刷新窗口列表（保留选择）。"""
        def _refresh():
            # 保存当前选择的 hwnd
            selected_hwnds = {h for h, _ in self._selected}
            # 刷新
            self.win_list.delete(0, "end")
            self._windows = []
            kw = self.filter_var.get().strip().lower()
            for hwnd, title in enum_windows():
                if kw and kw not in title.lower():
                    continue
                self._windows.append((hwnd, title))
                mark = " [需前台]" if needs_foreground(hwnd) else ""
                self.win_list.insert("end", f"[{hwnd}]{mark} {title}")
            # 恢复选择
            for i, (hwnd, _) in enumerate(self._windows):
                if hwnd in selected_hwnds:
                    self.win_list.select_set(i)
            self._update_selection()
            # 30 秒后再刷新
            self.root.after(30000, _refresh)

        self.root.after(30000, _refresh)

    def select_all(self):
        self.win_list.select_set(0, "end")
        self._update_selection()

    def clear_selection(self):
        self.win_list.select_clear(0, "end")
        self._update_selection()

    def on_select_window(self, _evt=None):
        self._update_selection()

    def _update_selection(self):
        sel_indices = self.win_list.curselection()
        # 如果 Listbox 没有焦点（比如用户点击了其他输入框），保留之前的选择
        if not sel_indices and not self._listbox_has_focus:
            return
        self._selected = []
        if not sel_indices:
            self.selected_var.set("0 个")
            self.bottom_status.set("未选择任何窗口。")
            return
        for i in sel_indices:
            if i < len(self._windows):
                self._selected.append(self._windows[i])
        has_fg = any(needs_foreground(h) for h, _ in self._selected)
        if has_fg and self.mode_var.get() != "bg":
            self.mode_var.set("fg")
        names = ", ".join(t[:20] for _, t in self._selected[:3])
        extra = f" +{len(self._selected)-3}更多" if len(self._selected) > 3 else ""
        self.selected_var.set(f"{len(self._selected)} 个: {names}{extra}")
        self.bottom_status.set(f"已选择 {len(self._selected)} 个窗口")

    # ---- 启动 / 停止 ----
    def _validate_inputs(self):
        """验证输入，返回 (hh, mm, count, interval, win_gap) 或 None。"""
        t = self.time_var.get().strip()
        try:
            hh, mm = [int(x) for x in t.split(":")]
            assert 0 <= hh <= 23 and 0 <= mm <= 59
        except Exception:
            messagebox.showerror("错误", "时间格式不对，应为 HH:MM，如 05:00")
            return None
        try:
            count = int(self.count_var.get())
            interval = float(self.interval_var.get())
            win_gap = float(self.win_gap_var.get())
            assert count >= 1 and interval > 0 and win_gap >= 0
        except Exception:
            messagebox.showerror("错误", "次数、间隔和窗口间隔需为正数。")
            return None
        return hh, mm, count, interval, win_gap

    def start(self):
        if not self._selected:
            messagebox.showwarning("提示", "请先选择至少一个目标窗口（可 Ctrl/Shift 多选）。")
            return
        params = self._validate_inputs()
        if not params:
            return
        hh, mm, count, interval, win_gap = params

        self._save_config_from_ui()  # 保存配置

        self.stop_evt = threading.Event()
        self.scheduler = SchedulerThread(
            list(self._selected), f"{hh:02d}:{mm:02d}", count, interval,
            win_gap, self.mode_var.get(), self.restore_var.get(),
            self.log_q, self.stop_evt, self.next_trigger_var)
        self.scheduler.start()
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.status_var.set(f"定时中… {len(self._selected)} 个窗口 → {hh:02d}:{mm:02d}")
        self.bottom_status.set(f"已启动定时任务，到 {hh:02d}:{mm:02d} 自动发送")

    def stop(self):
        if self.stop_evt:
            self.stop_evt.set()
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.status_var.set("已停止")
        self.next_trigger_var.set("-")
        self._push_log("用户点击停止。")
        self.bottom_status.set("已停止。")

    def test_send(self):
        """测试发送（不改变定时计划）。"""
        if not self._selected:
            messagebox.showwarning("提示", "请先选择至少一个目标窗口。")
            return
        self._do_send("测试")

    def execute_now(self):
        """立即执行一次（不影响定时计划）。"""
        if not self._selected:
            messagebox.showwarning("提示", "请先选择至少一个目标窗口。")
            return
        self._do_send("立即执行")

    def _do_send(self, label):
        """执行一次发送。"""
        mode = self.mode_var.get()
        self._push_log(f"{label}: 用 {MODE_DESC[mode]} 向 {len(self._selected)} 个窗口各发 1 次回车…")
        ok_count = 0
        for hwnd, title in self._selected:
            t = title if len(title) <= 25 else title[:23] + "…"
            try:
                used = send_enter(hwnd, 1, mode=mode, restore=self.restore_var.get())
                self._push_log(f"  ✓ [{hwnd}] {t} ({used})")
                ok_count += 1
            except Exception as e:
                self._push_log(f"  ✗ [{hwnd}] {t} ({e})")
            time.sleep(0.3)
        self._push_log(f"{label}完成: {ok_count}/{len(self._selected)} 成功。")

    # ---- 日志 ----
    def _push_log(self, msg):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        self.log_q.put(line)
        _log_to_file(line)

    def _poll_log(self):
        try:
            while True:
                msg = self.log_q.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", msg + "\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(200, self._poll_log)


def resource_path(rel):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def main():
    root = tk.Tk()
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
