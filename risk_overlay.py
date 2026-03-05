"""
risk_overlay.py —— 实时风控状态悬浮窗

原理：通过 CDP（Chrome 调试协议）被动订阅 Network 事件，
      接收浏览器里已有请求的响应拷贝，不产生任何额外网络请求。
      风控 JS 运行在浏览器渲染进程，对此工具的存在完全无感知。

使用：
    python risk_overlay.py              # 自动连接 Nstbrowser 第一个运行页面
    python risk_overlay.py --port 23511 # 指定 CDP 端口
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import threading
import time
import tkinter as tk
from collections import deque
from datetime import datetime

# ── 路径修正 ──────────────────────────────────────────────────────────────────
_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)
os.chdir(_DIR)
if hasattr(os, "add_dll_directory"):
    _py = os.path.join(_DIR, "python")
    if os.path.isdir(_py):
        os.add_dll_directory(_py)

import requests as _requests
import websockets

import config

# ── 监听域名 ──────────────────────────────────────────────────────────────────
WATCH = (
    "gigya.com",
    "id.pokemoncenter-online.com",
)

# ── 风控 Cookie 关键字 ────────────────────────────────────────────────────────
COOKIE_KEYS = ("glt_", "gig_bootstrap", "gig_hasSession", "hoPvmDpa", "_td")

# ── ANSI → tkinter tag 映射（不用 ANSI，直接给颜色） ──────────────────────────
C_GREEN  = "#44cc88"
C_YELLOW = "#f0c040"
C_RED    = "#ff6666"
C_CYAN   = "#7ec8e3"
C_GRAY   = "#555566"
C_WHITE  = "#c0caf5"
C_ORANGE = "#ff9944"

GIGYA_ERRORS = {
    0:      (C_GREEN,  "✔ 通过"),
    401002: (C_YELLOW, "密码错误"),
    401022: (C_YELLOW, "⚠ 待重置密码"),
    403010: (C_RED,    "reCAPTCHA 失败"),
    403047: (C_RED,    "账号锁定"),
    403100: (C_RED,    "账号封禁"),
    403101: (C_YELLOW, "📧 MFA 待验证"),
    403102: (C_RED,    "🚨 设备/IP 风控拦截"),
    403200: (C_RED,    "apiKey 拒绝"),
    500001: (C_RED,    "服务器错误"),
}


# ─────────────────────────────────────────────────────────────────────────────
#  数据结构（在子线程里填写，主线程只读）
# ─────────────────────────────────────────────────────────────────────────────
class RiskState:
    """线程安全的风控状态容器（只用 GIL，够用了）"""
    def __init__(self):
        self.connected     = False
        self.page_url      = "—"
        self.events: deque = deque(maxlen=30)   # (time_str, label, color, text)
        self.cookies: dict = {}                 # name → value[:40]
        self.last_login_err: int | None = None
        self.last_login_uid: str = ""
        self.bot_suspected: bool | None = None
        self.risk_score: str = "—"
        self.ids_403_count: int = 0
        self.updated_at    = 0.0

    def push(self, label: str, color: str, text: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.events.append((ts, label, color, text))
        self.updated_at = time.time()


_state = RiskState()

# ─────────────────────────────────────────────────────────────────────────────
#  CDP 核心：在 asyncio 子线程里运行
# ─────────────────────────────────────────────────────────────────────────────
def _label_url(url: str) -> tuple[str, str]:
    """返回 (label, color)"""
    if "id.pokemoncenter-online.com" in url:
        if "accounts.login" in url:   return "Gigya·login",   C_CYAN
        if "accounts.tfa"   in url:   return "Gigya·tfa",     C_YELLOW
        if "accounts."      in url:   return "Gigya·IDS",     C_GRAY
        if "sdk.config"     in url:   return "Gigya·sdk",     C_GRAY
        return "Gigya·IDS", C_GRAY
    if "gigya.com" in url:
        if "accounts.login" in url:   return "Gigya·login",   C_CYAN
        if "accounts.tfa"   in url:   return "Gigya·tfa",     C_YELLOW
        if "bootloader" in url or "bootstrap" in url:
            return "Gigya·boot", C_GRAY
        return "Gigya", C_WHITE
    return "?", C_GRAY


async def _cdp_session(ws_url: str):
    """单个 CDP WebSocket 会话，被动监听 Network 事件。"""
    # requestId → (url, label, color, status)
    pending: dict[str, tuple] = {}
    # CDP 命令 id → Future（用于等待特定响应）
    waiters: dict[int, asyncio.Future] = {}
    _cmd_id = 0

    def next_id() -> int:
        nonlocal _cmd_id
        _cmd_id += 1
        return _cmd_id

    async def send(ws, method, params=None) -> int:
        cid = next_id()
        await ws.send(json.dumps({"id": cid, "method": method,
                                  "params": params or {}}))
        return cid

    async def call(ws, method, params=None):
        """发送命令并等待对应 id 的响应。"""
        cid = next_id()
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        waiters[cid] = fut
        await ws.send(json.dumps({"id": cid, "method": method,
                                  "params": params or {}}))
        try:
            return await asyncio.wait_for(fut, timeout=4.0)
        except asyncio.TimeoutError:
            waiters.pop(cid, None)
            return {}

    try:
        async with websockets.connect(
            ws_url,
            max_size=10 * 1024 * 1024,
            ping_interval=20,
            ping_timeout=30,
        ) as ws:
            _state.connected = True
            await send(ws, "Network.enable")

            async for raw in ws:
                msg = json.loads(raw)

                # ── 命令响应 → 唤醒等待的 Future ─────────────────────────────
                msg_id = msg.get("id")
                if msg_id and msg_id in waiters:
                    fut = waiters.pop(msg_id)
                    if not fut.done():
                        fut.set_result(msg.get("result", {}))
                    continue

                method = msg.get("method", "")

                # ── 响应头到达 ────────────────────────────────────────────────
                if method == "Network.responseReceived":
                    p   = msg["params"]
                    url = p["response"]["url"]
                    if any(d in url for d in WATCH):
                        label, color = _label_url(url)
                        if label in ("Gigya·sdk", "Gigya·boot"):
                            continue
                        status = p["response"]["status"]
                        pending[p["requestId"]] = (url, label, color, status)
                        if status == 403 and "IDS" in label:
                            _state.ids_403_count += 1
                            _state.push(label, C_RED,
                                        f"HTTP 403 ← session校验失败！({_state.ids_403_count}次)")

                # ── 响应体已加载完整 ──────────────────────────────────────────
                elif method == "Network.loadingFinished":
                    req_id = msg["params"]["requestId"]
                    if req_id in pending:
                        url, label, color, status = pending.pop(req_id)
                        # 取 body（inline await，单连接串行）
                        if status < 400:
                            result = await call(ws, "Network.getResponseBody",
                                                {"requestId": req_id})
                            body = result.get("body", "")
                        else:
                            body = ""
                        await _process_body(body, url, label, color, status)

                # ── 页面导航 ──────────────────────────────────────────────────
                elif method in ("Page.frameNavigated",
                                "Page.navigatedWithinDocument"):
                    fr = (msg["params"].get("frame")
                          or msg["params"].get("url", ""))
                    if isinstance(fr, dict):
                        _state.page_url = fr.get("url", _state.page_url)
                    elif isinstance(fr, str) and fr.startswith("http"):
                        _state.page_url = fr
                    _state.updated_at = time.time()

    except Exception as ex:
        _state.connected = False
        _state.push("CDP", C_RED, f"连接断开: {type(ex).__name__}: {ex}")


async def _process_body(body: str, url: str, label: str, color: str, status: int):
    """解析 Gigya JSON 响应体，更新全局风控状态。"""
    p = {}
    if body:
        try:
            s = body.strip()
            start = s.find("{")
            end   = s.rfind("}") + 1
            if start != -1 and end > start:
                p = json.loads(s[start:end])
        except Exception:
            pass

    err = p.get("errorCode", "?")
    msg = p.get("errorMessage") or p.get("statusReason") or ""
    uid = p.get("UID") or p.get("uid") or ""

    err_color, err_meaning = GIGYA_ERRORS.get(err, (C_YELLOW, "未知"))

    if uid:
        _state.last_login_uid = uid[:20]
    if isinstance(err, int) and "login" in url.lower():
        _state.last_login_err = err
    if "isBotSuspected" in p:
        _state.bot_suspected = p["isBotSuspected"]
    if "riskAssessment" in p:
        _state.risk_score = str(p["riskAssessment"])

    text = f"HTTP {status}  errorCode={err}  {err_meaning}"
    if msg and err != 0:
        text += f"  ({msg[:40]})"
    if uid:
        text += f"  UID={uid[:14]}…"

    _state.push(label, err_color if isinstance(err, int) else color, text)

    if err == 403102:
        _state.push("🚨 BLOCK", C_RED, "设备/IP 被风控拦截！登录被拒绝！")
    if status == 429:
        _state.push("⚠️ 429", C_ORANGE, "请求频率过高（rate limit）")


# ─────────────────────────────────────────────────────────────────────────────
#  CDP 连接调度（自动发现运行中页面）
# ─────────────────────────────────────────────────────────────────────────────
def _get_ws_url(port: int) -> str | None:
    """从 Chrome DevTools /json/list 找到 pokemoncenter 或第一个普通页面。"""
    try:
        resp = _requests.get(f"http://127.0.0.1:{port}/json/list", timeout=4)
        pages = resp.json()
        if not pages:
            return None
        # 优先选 pokemoncenter 页面
        for p in pages:
            if "pokemoncenter" in p.get("url", ""):
                _state.page_url = p["url"]
                return p["webSocketDebuggerUrl"]
        # fallback: 第一个 page 类型
        for p in pages:
            if p.get("type") == "page":
                _state.page_url = p.get("url", "")
                return p["webSocketDebuggerUrl"]
        return pages[0].get("webSocketDebuggerUrl")
    except Exception as e:
        _state.push("CDP", C_RED, f"获取页面列表失败: {e}")
        return None


async def _cdp_loop(port: int):
    """持续监控，断线自动重连。"""
    while True:
        _state.connected = False
        ws_url = _get_ws_url(port)
        if not ws_url:
            _state.push("CDP", C_YELLOW, f"port {port} 未找到可用页面，5s 后重试…")
            await asyncio.sleep(5)
            continue
        _state.push("CDP", C_GREEN, f"已连接 ← {ws_url[:60]}")
        await _cdp_session(ws_url)
        _state.push("CDP", C_YELLOW, "连接断开，3s 后重试…")
        await asyncio.sleep(3)



# ─────────────────────────────────────────────────────────────────────────────
#  tkinter 悬浮窗
# ─────────────────────────────────────────────────────────────────────────────
class RiskOverlay(tk.Tk):
    W, H = 420, 540

    def __init__(self, port: int):
        super().__init__()
        self._port = port

        self.title("Risk Monitor")
        self.overrideredirect(True)
        self.wm_attributes("-topmost", True)
        self.wm_attributes("-alpha", 0.92)
        self.configure(bg="#0d1117")

        # 初始位置：右下角
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{self.W}x{self.H}+{sw - self.W - 20}+{sh - self.H - 60}")
        self.minsize(340, 400)

        self._build_ui()
        self._drag_x = self._drag_y = 0
        self.after(200, self._refresh)

    # ── UI 骨架 ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        # 顶栏
        bar = tk.Frame(self, bg="#161b22", height=24)
        bar.pack(fill="x")
        bar.bind("<ButtonPress-1>", self._ds)
        bar.bind("<B1-Motion>",     self._dm)

        self.lbl_conn = tk.Label(
            bar, text="⬤  连接中…",
            bg="#161b22", fg="#555", font=("Consolas", 9, "bold"), anchor="w",
        )
        self.lbl_conn.pack(side="left", padx=6)

        self.lbl_clock = tk.Label(
            bar, text="", bg="#161b22", fg="#444",
            font=("Consolas", 8), anchor="e",
        )
        self.lbl_clock.pack(side="right", padx=6)

        tk.Button(
            bar, text=" × ", bg="#161b22", fg="#555",
            bd=0, activebackground="#ff4444", activeforeground="white",
            font=("Consolas", 11), cursor="hand2",
            command=self.destroy,
        ).pack(side="right")

        body = tk.Frame(self, bg="#0d1117", padx=10, pady=6)
        body.pack(fill="both", expand=True)

        # URL 行
        url_row = tk.Frame(body, bg="#0d1117")
        url_row.pack(fill="x", pady=(0, 3))
        tk.Label(url_row, text="页面:", bg="#0d1117", fg="#444",
                 font=("Consolas", 8), width=5, anchor="w").pack(side="left")
        self.lbl_url = tk.Label(
            url_row, text="—", bg="#0d1117", fg="#6b7280",
            font=("Consolas", 8), anchor="w", wraplength=360, justify="left",
        )
        self.lbl_url.pack(side="left", fill="x", expand=True)

        _sep(body)

        # ── 风控指标格 ────────────────────────────────────────────────────────
        kpi = tk.Frame(body, bg="#0d1117")
        kpi.pack(fill="x", pady=(2, 4))

        self.kpi_login   = _kpi_cell(kpi, "登录结果", "—",     0)
        self.kpi_bot     = _kpi_cell(kpi, "Bot检测",  "—",     1)
        self.kpi_risk    = _kpi_cell(kpi, "风险评分",  "—",    2)
        self.kpi_403     = _kpi_cell(kpi, "IDS 403", "0 次",  3)
        for i in range(4):
            kpi.columnconfigure(i, weight=1)

        _sep(body)

        # ── Cookie 状态 ───────────────────────────────────────────────────────
        tk.Label(body, text="风控 Cookie", bg="#0d1117", fg="#444",
                 font=("Consolas", 7), anchor="w").pack(fill="x")

        self.ck_frame = tk.Frame(body, bg="#0d1117")
        self.ck_frame.pack(fill="x", pady=(2, 4))
        # Cookie 行动态创建，先用 dict 存
        self._ck_labels: dict[str, tuple[tk.Label, tk.Label]] = {}

        _sep(body)

        # ── 事件流 ────────────────────────────────────────────────────────────
        tk.Label(body, text="实时事件流", bg="#0d1117", fg="#444",
                 font=("Consolas", 7), anchor="w").pack(fill="x")

        self.evt_box = tk.Text(
            body, bg="#050509", fg="#8892b0",
            font=("Consolas", 8), bd=0,
            state="disabled", wrap="none", height=14,
            padx=4, pady=4,
        )
        sb = tk.Scrollbar(body, orient="vertical",
                          command=self.evt_box.yview)
        self.evt_box.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.evt_box.pack(fill="both", expand=True)

    # ── 拖拽 ─────────────────────────────────────────────────────────────────
    def _ds(self, e):
        self._drag_x = e.x_root - self.winfo_x()
        self._drag_y = e.y_root - self.winfo_y()

    def _dm(self, e):
        self.geometry(f"+{e.x_root - self._drag_x}+{e.y_root - self._drag_y}")

    # ── 刷新 ─────────────────────────────────────────────────────────────────
    def _refresh(self):
        try:
            self._do_refresh()
        except Exception:
            pass
        self.after(800, self._refresh)

    def _do_refresh(self):
        s = _state

        # 连接状态
        if s.connected:
            self.lbl_conn.configure(text="⬤  已连接", fg=C_GREEN)
        else:
            self.lbl_conn.configure(text="⬤  未连接", fg="#555")
        self.lbl_clock.configure(
            text=f"port {self._port}  {datetime.now():%H:%M:%S}"
        )

        # 页面 URL（截短）
        url = s.page_url
        if len(url) > 55:
            url = "…" + url[-52:]
        self.lbl_url.configure(text=url)

        # KPI
        if s.last_login_err is not None:
            c, txt = GIGYA_ERRORS.get(s.last_login_err, (C_YELLOW, "未知"))
            self.kpi_login[1].configure(text=f"{s.last_login_err} {txt}", fg=c)
        if s.bot_suspected is not None:
            if s.bot_suspected:
                self.kpi_bot[1].configure(text="🚨 True", fg=C_RED)
            else:
                self.kpi_bot[1].configure(text="✔ False", fg=C_GREEN)
        if s.risk_score != "—":
            self.kpi_risk[1].configure(text=s.risk_score, fg=C_YELLOW)
        if s.ids_403_count > 0:
            c = C_RED if s.ids_403_count > 0 else C_GREEN
            self.kpi_403[1].configure(text=f"{s.ids_403_count} 次", fg=c)

        # Cookie（从 CDP 事件里读取）
        self._update_cookies()

        # 事件流
        self.evt_box.configure(state="normal")
        self.evt_box.delete("1.0", "end")
        for ts, label, color, text in list(s.events):
            line = f"{ts}  [{label}]  {text}\n"
            tag  = f"c_{color.replace('#','')}"
            self.evt_box.insert("end", line, tag)
            self.evt_box.tag_configure(tag, foreground=color)
        self.evt_box.see("end")
        self.evt_box.configure(state="disabled")

    def _update_cookies(self):
        """从 _state.cookies 更新 Cookie 格子（按需动态创建行）。"""
        for name, val in _state.cookies.items():
            if name not in self._ck_labels:
                row = tk.Frame(self.ck_frame, bg="#0d1117")
                row.pack(fill="x")
                nl = tk.Label(row, text=name[:28], bg="#0d1117", fg="#444",
                              font=("Consolas", 7), width=28, anchor="w")
                nl.pack(side="left")
                vl = tk.Label(row, text="", bg="#0d1117",
                              font=("Consolas", 7), anchor="w")
                vl.pack(side="left")
                self._ck_labels[name] = (nl, vl)
            _, vl = self._ck_labels[name]
            disp = val[:36] if val else "（空）"
            col  = C_GREEN if val else C_RED
            vl.configure(text=disp, fg=col)


# ─────────────────────────────────────────────────────────────────────────────
def _kpi_cell(parent, title: str, default: str, col: int):
    f = tk.Frame(parent, bg="#161b22", padx=4, pady=4, relief="flat")
    f.grid(row=0, column=col, sticky="nsew", padx=2)
    tk.Label(f, text=title, bg="#161b22", fg="#444",
             font=("Consolas", 7), anchor="w").pack(fill="x")
    v = tk.Label(f, text=default, bg="#161b22", fg="#6b7280",
                 font=("Consolas", 9, "bold"), anchor="w", wraplength=90)
    v.pack(fill="x")
    return f, v


def _sep(parent):
    tk.Frame(parent, bg="#21262d", height=1).pack(fill="x", pady=3)


# ─────────────────────────────────────────────────────────────────────────────
#  CDP Cookie 轮询（独立协程，每 5s 读一次全量 Cookie）
# ─────────────────────────────────────────────────────────────────────────────
async def _cookie_poller(port: int):
    """每 5s 通过 CDP 读一次全量 Cookie，提取风控相关键写入 _state。"""
    while True:
        await asyncio.sleep(5)
        ws_url = _get_ws_url(port)
        if not ws_url:
            continue
        try:
            async with websockets.connect(ws_url, max_size=4*1024*1024,
                                          open_timeout=3) as ws:
                mid = 1
                await ws.send(json.dumps({
                    "id": mid,
                    "method": "Network.getAllCookies",
                    "params": {},
                }))
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("id") == mid:
                        cookies = msg.get("result", {}).get("cookies", [])
                        new_ck  = {}
                        for c in cookies:
                            n = c.get("name", "")
                            if any(k in n for k in COOKIE_KEYS):
                                new_ck[n] = c.get("value", "")[:40]
                        _state.cookies = new_ck
                        break
        except Exception:
            pass


async def _main_async(port: int):
    await asyncio.gather(
        _cdp_loop(port),
        _cookie_poller(port),
    )


# ─────────────────────────────────────────────────────────────────────────────
def _get_port(cli_port: int | None) -> int:
    if cli_port:
        return cli_port
    # 从 Nstbrowser API 获取第一个运行中浏览器的端口
    try:
        resp = _requests.get(
            f"http://{config.NST_HOST}/api/v2/browsers/running",
            headers={"x-api-key": config.NST_API_KEY},
            timeout=4,
        )
        data = resp.json()
        browsers = data.get("data", {}).get("list") or data.get("data") or []
        if isinstance(browsers, list) and browsers:
            b = browsers[0]
            p = b.get("port") or b.get("debugPort")
            if p:
                return int(p)
    except Exception:
        pass
    return 23511


# ─────────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(
        description="AutoPokemon 实时风控悬浮窗（CDP 被动监听，零额外请求）"
    )
    ap.add_argument("--port", type=int, default=None,
                    help="Nstbrowser CDP 端口（默认自动检测）")
    args = ap.parse_args()

    port = _get_port(args.port)
    print(f"[RiskOverlay] 连接 CDP port={port}")

    # asyncio 在后台线程
    t = threading.Thread(
        target=lambda: asyncio.run(_main_async(port)),
        daemon=True,
    )
    t.start()

    # tkinter 在主线程
    app = RiskOverlay(port)
    app.mainloop()


if __name__ == "__main__":
    main()
