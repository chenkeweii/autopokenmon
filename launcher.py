"""
launcher.py -- AutoPokemon 图形启动器
只有这一个文件需要编译成 EXE，其余源码保持 .py 可直接编辑。
"""
from __future__ import annotations
import os
import re
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox, ttk

# -- 路径 -------------------------------------------------------------------
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(BASE_DIR, "config.py")

def _find_python() -> str:
    candidates = [
        os.path.join(BASE_DIR, "python", "python.exe"),
        os.path.join(BASE_DIR, "venv", "Scripts", "python.exe"),
    ]
    # 非 frozen 模式才把当前解释器纳入候选（frozen 时 sys.executable 是 EXE 自身）
    if not getattr(sys, "frozen", False):
        candidates.append(sys.executable)
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    # 最后尝试 PATH 中的 python
    import shutil
    found = shutil.which("python") or shutil.which("python3")
    return found if found else "python"

PYTHON = _find_python()

# -- 配置字段定义 -------------------------------------------------------------
CONFIG_FIELDS = [
    ("NST_API_KEY",           "Nstbrowser API Key",  "str",  "Nstbrowser 客户端->设置->API Key"),
    ("CONCURRENT_BROWSERS",   "并发浏览器数",         "int",  "同时跑几个指纹浏览器"),
    ("LOTTERY_TARGET_TITLE",  "目标商品标题",         "str",  "与页面卡片文字完全一致"),
    ("OTP_EMAIL_ADDR",        "OTP 收件邮箱",         "str",  "接收验证码转发的邮箱"),
    ("OTP_EMAIL_AUTH_CODE",   "OTP 邮箱授权码",       "str",  "邮箱 IMAP 授权码"),
    ("EMAIL_OTP_WAIT",        "等待验证码超时(秒)",    "int",  ""),
    ("NOTIFY_ENABLED",        "启用通知",             "bool", ""),
    ("NOTIFY_TO_EMAIL",       "通知接收邮箱",         "str",  ""),
    ("DO_CLICK_LOGIN",        "真实点击登录",         "bool", "False=调试模式"),
    ("REQUIRE_OTP",           "执行验证码流程",       "bool", "False=跳过验证码"),
    ("REQUIRE_APPOINT_EMAIL", "等待预约确认邮件",     "bool", "True=收到邮件才算成功"),
    ("MIN_RETRY_INTERVAL",    "封IP重试间隔(秒)",     "int",  "默认3600"),
]

# -- 读写 config.py ----------------------------------------------------------
def read_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {}
    text = open(CONFIG_PATH, encoding="utf-8").read()
    result: dict = {}
    for key, *_ in CONFIG_FIELDS:
        m = re.search(rf'^{key}\s*=\s*(.+?)(?:\s*#.*)?$', text, re.MULTILINE)
        if m:
            raw = m.group(1).strip().strip('"').strip("'")
            result[key] = raw
    return result

def write_config(updates: dict) -> None:
    text = open(CONFIG_PATH, encoding="utf-8").read()
    for key, value_str in updates.items():
        text = re.sub(
            rf'^({key}\s*=\s*)(.+?)(\s*(?:#.*)?)$',
            lambda m, v=value_str: m.group(1) + v + m.group(3),
            text, flags=re.MULTILINE,
        )
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(text)
    messagebox.showinfo("已保存", "配置已写入 config.py")

# -- 启动脚本 ----------------------------------------------------------------
def launch_script(script: str) -> None:
    path = os.path.join(BASE_DIR, script)
    if not os.path.exists(path):
        messagebox.showerror("错误", f"找不到脚本：{path}")
        return

    py_dir = os.path.dirname(PYTHON)
    os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)

    # 写临时 bat：chcp 65001 防乱码，PATH 含 python\ 确保 DLL 能找到
    bat = os.path.join(BASE_DIR, f"_run_{script}.bat")
    with open(bat, "w", encoding="utf-8") as f:
        f.write("@echo off\n")
        f.write("chcp 65001 > nul\n")
        f.write(f'cd /d "{BASE_DIR}"\n')
        f.write(f'set PATH={py_dir};%PATH%\n')
        f.write(f'set PYTHONHOME=\n')
        f.write(f'set PYTHONPATH={BASE_DIR}\n')
        f.write(f'set PLAYWRIGHT_BROWSERS_PATH={os.path.join(BASE_DIR, "browsers")}\n')
        f.write(f'echo 启动 {script} ...\n')
        f.write(f'echo ----------------------------------------\n')
        f.write(f'"{PYTHON}" "{path}"\n')
        f.write(f'echo ----------------------------------------\n')
        f.write(f'echo 脚本已结束，退出码: %ERRORLEVEL%\n')
        f.write(f'pause\n')

    subprocess.Popen(
        f'start "AutoPokemon - {script}" cmd /c "{bat}"',
        shell=True, cwd=BASE_DIR,
    )

# -- UI ----------------------------------------------------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AutoPokemon 启动器")
        self.resizable(True, True)
        self.minsize(520, 500)
        self._center(620, 640)
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        nb.add(self._make_run_tab(nb),    text="  运行  ")
        nb.add(self._make_config_tab(nb), text="  配置  ")

    def _center(self, w, h):
        self.update_idletasks()
        x = (self.winfo_screenwidth()  - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _make_run_tab(self, parent):
        f = tk.Frame(parent, padx=20, pady=20)
        tk.Label(f, text="AutoPokemon", font=("微软雅黑", 17, "bold")).pack(pady=(10,4))
        tk.Label(f, text="宝可梦官网自动抽选预约系统", font=("微软雅黑", 10), fg="#666").pack(pady=(0,24))
        btn = dict(font=("微软雅黑", 12), width=26, height=2, cursor="hand2", relief="flat")
        tk.Button(f, text="▶  运行主程序 (main.py)",
                  bg="#4CAF50", fg="white", activebackground="#45a049",
                  command=lambda: launch_script("main.py"), **btn).pack(pady=6)
        tk.Button(f, text="⚙  新增指纹环境 (setup_profiles.py)",
                  bg="#2196F3", fg="white", activebackground="#1976D2",
                  command=lambda: launch_script("setup_profiles.py"), **btn).pack(pady=6)
        tk.Label(f, text=f"Python: {PYTHON}", font=("Consolas", 8),
                 fg="#aaa", wraplength=380).pack(pady=(24,0))
        return f

    def _make_config_tab(self, parent):
        outer = tk.Frame(parent)
        canvas = tk.Canvas(outer, borderwidth=0, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, padx=16, pady=10)
        win = canvas.create_window((0,0), window=inner, anchor="nw")

        def _cfg(e): canvas.configure(scrollregion=canvas.bbox("all"))
        inner.bind("<Configure>", _cfg)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))
        canvas.bind_all("<MouseWheel>",
            lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        cur = read_config()
        self._vars: dict = {}
        self._fmap = {f[0]: f for f in CONFIG_FIELDS}

        sections = [
            ("Nstbrowser",    ["NST_API_KEY","CONCURRENT_BROWSERS"]),
            ("目标商品",       ["LOTTERY_TARGET_TITLE"]),
            ("邮箱 / OTP",    ["OTP_EMAIL_ADDR","OTP_EMAIL_AUTH_CODE","EMAIL_OTP_WAIT"]),
            ("通知",           ["NOTIFY_ENABLED","NOTIFY_TO_EMAIL"]),
            ("运行开关",       ["DO_CLICK_LOGIN","REQUIRE_OTP","REQUIRE_APPOINT_EMAIL"]),
            ("重试参数",       ["MIN_RETRY_INTERVAL"]),
        ]

        for sec, keys in sections:
            hdr = tk.Frame(inner, bg="#e8f4fd", pady=3)
            hdr.pack(fill="x", pady=(8,2))
            tk.Label(hdr, text=sec, font=("微软雅黑",10,"bold"),
                     bg="#e8f4fd", padx=6).pack(anchor="w")
            for key in keys:
                _, label, typ, hint = self._fmap[key]
                raw = cur.get(key, "")
                row = tk.Frame(inner)
                row.pack(fill="x", pady=3)
                tk.Label(row, text=label, width=14, anchor="w",
                         font=("微软雅黑",9)).pack(side="left")
                if typ == "bool":
                    var = tk.BooleanVar(value=(raw == "True"))
                    tk.Checkbutton(row, variable=var).pack(side="left")
                else:
                    var = tk.StringVar(value=raw)
                    tk.Entry(row, textvariable=var, font=("微软雅黑",9),
                             width=28 if typ=="str" else 10).pack(side="left")
                if hint:
                    tk.Label(row, text=hint, font=("微软雅黑",8),
                             fg="#999", wraplength=180, justify="left").pack(side="left", padx=(6,0))
                self._vars[key] = var

        tk.Button(inner, text="  保存配置", font=("微软雅黑",11),
                  bg="#FF9800", fg="white", activebackground="#F57C00",
                  relief="flat", cursor="hand2", height=2,
                  command=self._save).pack(fill="x", pady=(16,4))
        return outer

    def _save(self):
        updates: dict = {}
        for key, var in self._vars.items():
            _, _, typ, _ = self._fmap[key]
            if typ == "bool":
                updates[key] = "True" if var.get() else "False"
            elif typ == "int":
                v = str(var.get()).strip()
                if not v.isdigit():
                    messagebox.showerror("格式错误", f"{key} 必须是整数")
                    return
                updates[key] = v
            else:
                updates[key] = f'"{str(var.get()).strip()}"'
        write_config(updates)

if __name__ == "__main__":
    App().mainloop()