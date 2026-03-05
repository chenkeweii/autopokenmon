"""
desk_monitor.py —— AutoPokemon 桌面悬浮状态窗

特点：
 * 纯本地读取 data/accounts.csv + logs/run_*.log，零网络请求
 * 风控系统完全无法感知此工具的存在
 * 始终置顶、半透明、可拖拽、可调大小
 * 每 1.5s 自动刷新

使用：
    python desk_monitor.py
"""

from __future__ import annotations

import csv
import glob
import os
import re
import sys
import time
import tkinter as tk
from tkinter import font as tkfont
from collections import deque
from datetime import datetime

# ── 路径修正 ──────────────────────────────────────────────────────────────────
_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)
os.chdir(_DIR)

ACCOUNTS_CSV = os.path.join(_DIR, "data", "accounts.csv")
LOGS_DIR     = os.path.join(_DIR, "logs")
REFRESH_MS   = 1500   # 刷新间隔（毫秒）
LOG_LINES    = 8      # 显示最近 N 条日志

# ── 状态码含义 ────────────────────────────────────────────────────────────────
STATUS_LABEL = {
    "0": ("⬜ 待处理", "#8888aa"),
    "1": ("✅ 预约成功", "#44cc88"),
    "2": ("⚫ 账号问题", "#888888"),
    "3": ("🔥 封禁待重试", "#ff6666"),
    "4": ("📧 待邮件确认", "#f0c040"),
    "5": ("💀 超时耗尽", "#ff4444"),
}

# ── 日志正则 ──────────────────────────────────────────────────────────────────
RE_ACCOUNT = re.compile(
    r"账号\s+([\w.@+-]+)\s*\|"
)
RE_STEP = re.compile(
    r"Step\s+[\d\w]+\s*\|\s*(.{0,80})"
)

# ─────────────────────────────────────────────────────────────────────────────
def read_csv_stats() -> dict:
    """读 accounts.csv，统计各 status 数量及最新 error 账号。"""
    counts = {k: 0 for k in STATUS_LABEL}
    total  = 0
    mfa_count = 0
    try:
        with open(ACCOUNTS_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                total += 1
                s = str(row.get("status", "0")).strip()
                counts[s] = counts.get(s, 0) + 1
                # MFA_REQUIRED 是 status=2 的子类型
                if "MFA_REQUIRED" in str(row.get("error_message", "")):
                    mfa_count += 1
    except Exception:
        pass
    return {"counts": counts, "total": total, "mfa": mfa_count}


def get_latest_log() -> str | None:
    """返回最新 run_*.log 的路径。"""
    files = glob.glob(os.path.join(LOGS_DIR, "run_*.log"))
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def tail_log(path: str, n: int = LOG_LINES) -> list[str]:
    """高效读取文件末尾 n 行（不读全文）。"""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            buf_size = min(8192, size)
            f.seek(-buf_size, 2)
            raw = f.read(buf_size)
        lines = raw.decode("utf-8", errors="replace").splitlines()
        return lines[-n:]
    except Exception:
        return []


def parse_log_state(lines: list[str]) -> dict:
    """从日志行里提取：当前账号、进行中步骤、最近事件。"""
    current_account = "—"
    current_step    = "—"
    events          = []

    for line in reversed(lines):
        if current_account == "—":
            m = RE_ACCOUNT.search(line)
            if m:
                current_account = m.group(1)
        if current_step == "—":
            m = RE_STEP.search(line)
            if m:
                current_step = m.group(1).strip()

        # 收集有价值的事件行（过滤无聊的行）
        skip_kw = ("DEBUG", "wait_for", "locator(", "evaluate(")
        if not any(k in line for k in skip_kw):
            # 抽取时间戳后的内容
            parts = line.split(" - ", 2)
            display = parts[-1] if len(parts) >= 2 else line
            display = display.strip()
            if display:
                events.append(display)
        if len(events) >= LOG_LINES:
            break

    return {
        "current_account": current_account,
        "current_step":    current_step,
        "events":          list(reversed(events)),
    }


def detect_script_running(log_path: str | None) -> bool:
    """判断主脚本是否正在运行：检查日志文件 30s 内有无新写入。"""
    if not log_path:
        return False
    try:
        mtime = os.path.getmtime(log_path)
        return (time.time() - mtime) < 30
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
class FloatMonitor(tk.Tk):
    def __init__(self):
        super().__init__()

        # ── 窗口属性 ──────────────────────────────────────────────────────────
        self.title("AutoPokemon Monitor")
        self.overrideredirect(True)   # 去掉标题栏
        self.wm_attributes("-topmost", True)       # 始终置顶
        self.wm_attributes("-alpha", 0.88)         # 透明度
        self.configure(bg="#12131a")
        self.geometry("360x460+50+80")
        self.minsize(300, 360)

        # ── 字体 ──────────────────────────────────────────────────────────────
        FONT_MONO  = ("Consolas", 9)
        FONT_TITLE = ("Consolas", 10, "bold")
        FONT_BIG   = ("Consolas", 16, "bold")
        FONT_SMALL = ("Consolas", 8)

        # ── 顶栏（拖拽 + 关闭）────────────────────────────────────────────────
        bar = tk.Frame(self, bg="#1e2030", height=22)
        bar.pack(fill="x")
        bar.bind("<ButtonPress-1>",   self._drag_start)
        bar.bind("<B1-Motion>",       self._drag_move)

        tk.Label(
            bar, text="  🎮 AutoPokemon Monitor",
            bg="#1e2030", fg="#7986cb",
            font=("Consolas", 9, "bold"), anchor="w",
        ).pack(side="left", fill="x", expand=True)

        tk.Button(
            bar, text=" × ", bg="#1e2030", fg="#888",
            bd=0, activebackground="#ff4444", activeforeground="white",
            font=("Consolas", 10), cursor="hand2",
            command=self.destroy,
        ).pack(side="right")

        # ── 内容区 ────────────────────────────────────────────────────────────
        body = tk.Frame(self, bg="#12131a", padx=10, pady=8)
        body.pack(fill="both", expand=True)

        # 运行状态指示灯
        status_row = tk.Frame(body, bg="#12131a")
        status_row.pack(fill="x")
        self.lbl_running = tk.Label(
            status_row, text="⬤  检测中...",
            bg="#12131a", fg="#888", font=FONT_TITLE, anchor="w",
        )
        self.lbl_running.pack(side="left")
        self.lbl_time = tk.Label(
            status_row, text="",
            bg="#12131a", fg="#555", font=FONT_SMALL, anchor="e",
        )
        self.lbl_time.pack(side="right")

        _sep(body)

        # 大号进度数字
        prog_row = tk.Frame(body, bg="#12131a")
        prog_row.pack(fill="x", pady=(2, 2))
        self.lbl_done = tk.Label(
            prog_row, text="0", bg="#12131a", fg="#44cc88",
            font=("Consolas", 28, "bold"),
        )
        self.lbl_done.pack(side="left")
        tk.Label(prog_row, text=" / ", bg="#12131a", fg="#555",
                 font=("Consolas", 20)).pack(side="left")
        self.lbl_total = tk.Label(
            prog_row, text="0", bg="#12131a", fg="#aaaacc",
            font=("Consolas", 22),
        )
        self.lbl_total.pack(side="left")
        tk.Label(prog_row, text="  账号", bg="#12131a", fg="#555",
                 font=FONT_MONO).pack(side="left", padx=(4, 0))

        # 进度条
        self.canvas_bar = tk.Canvas(body, bg="#1e2030", height=6,
                                    highlightthickness=0)
        self.canvas_bar.pack(fill="x", pady=(0, 6))

        _sep(body)

        # 状态统计格子
        grid_frame = tk.Frame(body, bg="#12131a")
        grid_frame.pack(fill="x", pady=(4, 4))
        self.stat_labels: dict[str, tk.Label] = {}
        order = [("1", "2"), ("3", "4"), ("5", "0")]
        for r, (k1, k2) in enumerate(order):
            for c, k in enumerate([k1, k2]):
                lbl_name, color = STATUS_LABEL.get(k, (k, "#888"))
                cell = tk.Frame(grid_frame, bg="#1a1b2a",
                                padx=4, pady=3, relief="flat")
                cell.grid(row=r, column=c, sticky="nsew", padx=2, pady=2)
                grid_frame.columnconfigure(c, weight=1)
                tk.Label(cell, text=lbl_name, bg="#1a1b2a",
                         fg=color, font=FONT_SMALL, anchor="w").pack(fill="x")
                v = tk.Label(cell, text="0", bg="#1a1b2a",
                             fg=color, font=("Consolas", 14, "bold"), anchor="e")
                v.pack(fill="x")
                self.stat_labels[k] = v

        _sep(body)

        # 当前账号 / 步骤
        self.lbl_cur_acc = _info_row(body, "当前账号", "—")
        self.lbl_cur_stp = _info_row(body, "当前步骤", "—")

        _sep(body)

        # 最近日志
        tk.Label(body, text="最近日志", bg="#12131a", fg="#555",
                 font=FONT_SMALL, anchor="w").pack(fill="x")
        self.log_box = tk.Text(
            body, bg="#0d0e18", fg="#8892b0",
            font=("Consolas", 7), bd=0, state="disabled",
            wrap="word", height=7, padx=4, pady=4,
        )
        self.log_box.pack(fill="both", expand=True, pady=(2, 0))

        # ── 拖拽状态 ──────────────────────────────────────────────────────────
        self._drag_x = 0
        self._drag_y = 0

        # ── 启动刷新循环 ──────────────────────────────────────────────────────
        self._refresh()

    # ── 拖拽 ─────────────────────────────────────────────────────────────────
    def _drag_start(self, e):
        self._drag_x = e.x_root - self.winfo_x()
        self._drag_y = e.y_root - self.winfo_y()

    def _drag_move(self, e):
        self.geometry(f"+{e.x_root - self._drag_x}+{e.y_root - self._drag_y}")

    # ── 刷新数据 ──────────────────────────────────────────────────────────────
    def _refresh(self):
        try:
            self._do_refresh()
        except Exception:
            pass
        self.after(REFRESH_MS, self._refresh)

    def _do_refresh(self):
        # ── 1. CSV 统计 ───────────────────────────────────────────────────────
        stats  = read_csv_stats()
        counts = stats["counts"]
        total  = stats["total"]
        done   = sum(counts.get(k, 0) for k in ("1", "2", "3", "4", "5"))
        success = counts.get("1", 0) + counts.get("4", 0)

        self.lbl_done.configure(text=str(done))
        self.lbl_total.configure(text=str(total))
        for k, lbl in self.stat_labels.items():
            v = counts.get(k, 0)
            lbl.configure(text=str(v))

        # 进度条
        pct = done / total if total else 0
        self.canvas_bar.delete("all")
        w = self.canvas_bar.winfo_width() or 340
        self.canvas_bar.create_rectangle(0, 0, w, 6, fill="#1e2030", outline="")
        if pct > 0:
            self.canvas_bar.create_rectangle(
                0, 0, int(w * pct), 6,
                fill="#44cc88" if pct < 1 else "#7986cb", outline="",
            )

        # ── 2. 日志状态 ───────────────────────────────────────────────────────
        log_path = get_latest_log()
        running  = detect_script_running(log_path)
        lines    = tail_log(log_path) if log_path else []
        state    = parse_log_state(lines)

        if running:
            self.lbl_running.configure(
                text="⬤  运行中", fg="#44cc88"
            )
        else:
            self.lbl_running.configure(
                text="⬤  空闲", fg="#555555"
            )
        self.lbl_time.configure(
            text=datetime.now().strftime("%H:%M:%S")
        )

        acc = state["current_account"]
        # 截断显示
        if len(acc) > 30:
            acc = acc[:27] + "..."
        self.lbl_cur_acc.configure(text=acc)

        stp = state["current_step"]
        if len(stp) > 34:
            stp = stp[:31] + "..."
        self.lbl_cur_stp.configure(text=stp)

        # ── 3. 日志框 ─────────────────────────────────────────────────────────
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        for ev in state["events"]:
            # 颜色标注
            if "✓" in ev or "成功" in ev or "预约成功" in ev:
                tag = "ok"
            elif "✗" in ev or "失败" in ev or "ERROR" in ev or "封禁" in ev:
                tag = "err"
            elif "WARNING" in ev or "警告" in ev:
                tag = "warn"
            else:
                tag = "norm"
            self.log_box.insert("end", ev + "\n", tag)
        self.log_box.tag_configure("ok",   foreground="#44cc88")
        self.log_box.tag_configure("err",  foreground="#ff6666")
        self.log_box.tag_configure("warn", foreground="#f0c040")
        self.log_box.tag_configure("norm", foreground="#8892b0")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")


# ─────────────────────────────────────────────────────────────────────────────
def _sep(parent):
    tk.Frame(parent, bg="#2a2b3a", height=1).pack(fill="x", pady=4)


def _info_row(parent, label: str, default: str) -> tk.Label:
    row = tk.Frame(parent, bg="#12131a")
    row.pack(fill="x", pady=1)
    tk.Label(row, text=f"{label}:", bg="#12131a", fg="#555",
             font=("Consolas", 8), width=8, anchor="w").pack(side="left")
    v = tk.Label(row, text=default, bg="#12131a", fg="#c0caf5",
                 font=("Consolas", 9), anchor="w")
    v.pack(side="left", fill="x", expand=True)
    return v


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = FloatMonitor()
    app.mainloop()
