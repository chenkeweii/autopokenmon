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

# ── 日志文件路径（由 --log 参数设置）─────────────────────────────────────────
_log_path:   str | None = None   # e.g. logs/risk_log.jsonl
_log_change: str        = "baseline"  # 当前改造标签

# ── 监听域名 ──────────────────────────────────────────────────────────────────
WATCH = (
    # Gigya / 身份风控
    "gigya.com",
    "id.pokemoncenter-online.com",
    # Treasure Data / 行为采集
    "treasuredata.com",
    # Salesforce Commerce Cloud / 电商行为追踪
    "cquotient.com",
    # Salesforce Marketing Cloud
    "igodigital.com",
    # Facebook Pixel / 广告追踪
    "connect.facebook.net",
    # Google Analytics / GTM
    "googletagmanager.com",
    "google-analytics.com",
)

# 仅记录事件流，不读 body（追踪像素类域名）
WATCH_PIXEL = (
    "connect.facebook.net",
    "googletagmanager.com",
    "google-analytics.com",
    "igodigital.com",
)

# ── 风控 Cookie 关键字 ────────────────────────────────────────────────────────
COOKIE_KEYS = (
    # Gigya
    "glt_", "gig_bootstrap", "gig_hasSession",
    # Pokemon Center 指纹
    "hoPvmDpa",
    # Treasure Data
    "_td",
    # Salesforce Commerce Cloud
    "__cq_", "cqcid", "cquid",
    # Facebook Pixel
    "_fbp",
    # Google Analytics
    "_ga",
)

# ── ANSI → tkinter tag 映射（不用 ANSI，直接给颜色） ──────────────────────────
C_GREEN  = "#3fb950"  # GitHub-dark 绿
C_YELLOW = "#e3b341"  # 琥珀黄
C_RED    = "#f85149"  # 亮红
C_CYAN   = "#58a6ff"  # 亮蓝
C_GRAY   = "#8b949e"  # 可读灰（原#555566太暗）
C_WHITE  = "#cdd9e5"  # 亮白
C_ORANGE = "#f0883e"  # 橙

GIGYA_ERRORS = {
    0:      (C_GREEN,  "✔ 成功"),
    200001: (C_GREEN,  "✔ 操作成功"),
    400006: (C_YELLOW, "参数缺失/无效"),
    400009: (C_YELLOW, "token 无效或已过期"),
    401002: (C_YELLOW, "密码错误"),
    401020: (C_YELLOW, "无效账号/邮箱"),
    401022: (C_YELLOW, "⚠ 需重置密码"),
    401030: (C_YELLOW, "账号未激活"),
    403003: (C_RED,    "apiKey 未授权"),
    403007: (C_RED,    "未登录 / 无会话"),
    403010: (C_RED,    "reCAPTCHA 失败"),
    403041: (C_RED,    "登录尝试过多"),
    403042: (C_RED,    "账号被暂时锁定"),
    403047: (C_RED,    "账号永久锁定"),
    403100: (C_RED,    "账号被封禁"),
    403101: (C_YELLOW, "📧 MFA 待验证"),
    403102: (C_RED,    "🚨 设备/IP 风控拦截"),
    403110: (C_RED,    "reCAPTCHA 分数过低"),
    403200: (C_RED,    "apiKey 不存在/被拒"),
    404000: (C_YELLOW, "账号不存在"),
    500001: (C_RED,    "Gigya 服务器内部错误"),
    500002: (C_RED,    "Gigya 服务暂时不可用"),
}

# ── Cookie 可读状态表 ─────────────────────────────────────────────────────────
# 顺序重要：长前缀必须在短前缀之前（_td_global 在 _td 前，__cq_ 在 cq 前）
_CK_ROWS = [
    # ── Gigya 身份风控 ──────────────────
    ("glt_",           "登录令牌",    "Gigya 登录会话凭证（有=已登录）"),
    ("gig_bootstrap",  "Bootstrap",   "Gigya 启动状态（id_ver4=身份已验证）"),
    ("gig_hasSession", "Gigya会话",   "true=会话活跃 / false=会话失效"),
    # ── Pokemon Center 设备指纹 ─────────
    ("hoPvmDpa",       "设备指纹",    "宝可梦官网设备指纹（缺失=高风险）"),
    # ── Treasure Data 行为追踪 ──────────
    ("_td_global",     "TD全局ID",   "Treasure Data 全局设备追踪"),
    ("_td",            "TD会话ID",   "Treasure Data 会话追踪"),
    # ── Salesforce Commerce Cloud ───────
    ("__cq_",          "SF会话",      "Salesforce CC 电商会话令牌"),
    ("cqcid",          "SF客户ID",   "Salesforce CC 客户标识"),
    ("cquid",          "SF用户ID",   "Salesforce CC 用户唯一ID"),
    # ── 广告/统计追踪 ────────────────────
    ("_fbp",           "FB像素",      "Facebook Pixel 广告追踪"),
    ("_ga",            "GA追踪",      "Google Analytics 统计追踪"),
]


def _ck_interpret(prefix: str, val: str):
    """返回 (状态文本, 颜色, 详情文本)  —— detail 不截断，由控件自动换行"""
    if prefix == "glt_":
        if val:
            tail = val[-32:] if len(val) > 32 else val
            return ("✔ 已签发", C_GREEN, f"…{tail}")
        return ("✗ 缺失", C_RED, "未登录 / 会话失效")

    if prefix == "gig_bootstrap":
        if val:
            note = "身份已验证" if "ver" in val else val
            return (val, C_CYAN, note)
        return ("✗ 无", C_RED, "")

    if prefix == "gig_hasSession":
        if val == "true":
            return ("✔ 有效", C_GREEN, "Gigya 会话活跃")
        if val == "false":
            return ("✗ 无会话", C_RED, "被踢出或未登录")
        return ("—", C_GRAY, "")

    if prefix == "hoPvmDpa":
        if val:
            return ("✔ 已设置", C_GREEN, val)
        return ("✗ 缺失", C_RED, "设备指纹丢失（风控高危）")

    if prefix in ("_td_global", "_td"):
        if val:
            return ("✔ 已设置", C_GRAY, val)
        return ("✗ 无", C_GRAY, "未被 TD 追踪")

    if prefix == "__cq_":
        if val:
            tail = val[-20:] if len(val) > 20 else val
            return ("✔ 有会话", C_GREEN, f"…{tail}")
        return ("✗ 无", C_YELLOW, "Salesforce CC 电商会话缺失")

    if prefix in ("cqcid", "cquid"):
        if val:
            return ("✔ 已标记", C_GRAY, val)
        return ("—", C_GRAY, "")

    if prefix == "_fbp":
        if val:
            return ("✔ 已设置", C_GRAY, val)
        return ("—", C_GRAY, "Facebook Pixel 未触发")

    if prefix == "_ga":
        if val:
            return ("✔ 已设置", C_GRAY, val)
        return ("—", C_GRAY, "GA 未追踪")

    if val:
        return ("✔", C_WHITE, val)
    return ("—", C_GRAY, "")


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
    # ── Gigya / 身份风控 ──
    if "id.pokemoncenter-online.com" in url:
        if "accounts.login" in url:   return "Gigya·login",  C_CYAN
        if "accounts.tfa"   in url:   return "Gigya·tfa",    C_YELLOW
        if "accounts."      in url:   return "Gigya·IDS",    C_GRAY
        return "Gigya·IDS", C_GRAY
    if "gigya.com" in url:
        if "accounts.login" in url:   return "Gigya·login",  C_CYAN
        if "accounts.tfa"   in url:   return "Gigya·tfa",    C_YELLOW
        if "bootloader" in url or "bootstrap" in url:
                                      return "Gigya·boot",   C_GRAY
        if "sdk.config" in url:       return "Gigya·sdk",    C_GRAY
        return "Gigya", C_WHITE
    # ── Treasure Data / 行为采集 ──
    if "treasuredata.com" in url:     return "TD·collect",   C_GRAY
    # ── Salesforce CC / 电商追踪 ──
    if "cquotient.com" in url:        return "SF·CC",        C_GRAY
    # ── Salesforce Marketing Cloud ──
    if "igodigital.com" in url:       return "SF·MktCloud",  C_GRAY
    # ── Facebook Pixel ──
    if "connect.facebook.net" in url: return "FB·Pixel",     C_GRAY
    # ── Google Analytics / GTM ──
    if "googletagmanager.com" in url: return "GTM",          C_GRAY
    if "google-analytics.com" in url: return "GA",           C_GRAY
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
                        is_pixel = any(d in url for d in WATCH_PIXEL)
                        pending[p["requestId"]] = (url, label, color, status, is_pixel)
                        if status == 403 and "IDS" in label:
                            _state.ids_403_count += 1
                            _state.push(label, C_RED,
                                        f"HTTP 403 ← session校验失败！({_state.ids_403_count}次)")
                        # 追踪像素：只记录异常（非200）状态
                        if is_pixel and status != 200:
                            _state.push(label, C_YELLOW,
                                        f"HTTP {status} ← 追踪请求异常")

                # ── 响应体已加载完整 ──────────────────────────────────────────
                elif method == "Network.loadingFinished":
                    req_id = msg["params"]["requestId"]
                    if req_id in pending:
                        url, label, color, status, is_pixel = pending.pop(req_id)
                        # 追踪像素不读 body，只在正常时记一条 debug 事件
                        if is_pixel:
                            if status == 200:
                                _state.push(label, C_GRAY, f"HTTP 200 ✔")
                            continue
                        # Gigya / TD / Salesforce 读 body
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


# ─────────────────────────────────────────────────────────────────────────────
#  基线日志（JSONL）
# ─────────────────────────────────────────────────────────────────────────────
def _append_log(entry: dict) -> None:
    """追加一行 JSON 到 risk_log.jsonl，如果 _log_path 为 None 则静默跳过。"""
    if not _log_path:
        return
    try:
        os.makedirs(os.path.dirname(_log_path) or ".", exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False)
        with open(_log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        pass  # 日志失败不影响主界面


async def _process_body(body: str, url: str, label: str, color: str, status: int):
    """解析响应体，更新全局风控状态。支持 Gigya JSON、TD、Salesforce CC。"""

    # ── 非 Gigya 域名：只看 HTTP 状态 ────────────────────────────────────────
    is_gigya = ("gigya.com" in url or "pokemoncenter-online.com" in url)
    if not is_gigya:
        if status == 200:
            ev_color = C_GREEN
            ev_text  = f"HTTP {status} ✔"
        elif status == 429:
            ev_color = C_ORANGE
            ev_text  = f"HTTP {status} ⚠ 频率限制"
        elif status >= 400:
            ev_color = C_RED
            ev_text  = f"HTTP {status} ✗ 请求被拒"
        else:
            ev_color = C_GRAY
            ev_text  = f"HTTP {status}"
        _state.push(label, ev_color, ev_text)
        return

    # ── Gigya / IDS：解析 JSON errorCode ─────────────────────────────────────
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

    err_color, err_meaning = GIGYA_ERRORS.get(err, (C_YELLOW, "未知码"))

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

    # ── 写入基线日志 ──────────────────────────────────────────────────────────
    if "login" in url.lower() or "accounts" in url.lower():
        ra = p.get("riskAssessment")
        _append_log({
            "ts":           datetime.now().isoformat(timespec="seconds"),
            "change":       _log_change,
            "url":          url,
            "errorCode":    err,
            "uid":          uid[:20] if uid else "",
            "botSuspected": p.get("isBotSuspected"),
            "riskScore":    ra.get("score") if isinstance(ra, dict) else ra,
            "riskAllow":    ra.get("allow") if isinstance(ra, dict) else None,
            "httpStatus":   status,
            "label":        label,
        })


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
    W, H = 520, 660

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
        self.minsize(380, 440)

        self._build_ui()
        self._drag_x = self._drag_y = 0
        # resize state
        self._rsz_x = self._rsz_y = 0
        self._rsz_w = self._rsz_h = 0
        self._minimized = False
        self.after(200, self._refresh)

    # ── UI 骨架 ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        # 顶栏
        bar = tk.Frame(self, bg="#161b22", height=28)
        bar.pack(fill="x")
        bar.bind("<ButtonPress-1>", self._ds)
        bar.bind("<B1-Motion>",     self._dm)

        self.lbl_conn = tk.Label(
            bar, text="⬤  连接中…",
            bg="#161b22", fg="#768390", font=("Consolas", 11, "bold"), anchor="w",
        )
        self.lbl_conn.pack(side="left", padx=8)

        self.lbl_clock = tk.Label(
            bar, text="", bg="#161b22", fg="#768390",
            font=("Consolas", 10), anchor="e",
        )
        self.lbl_clock.pack(side="right", padx=8)

        tk.Button(
            bar, text=" × ", bg="#161b22", fg="#8b949e",
            bd=0, activebackground="#f85149", activeforeground="white",
            font=("Consolas", 13), cursor="hand2",
            command=self.destroy,
        ).pack(side="right")

        self._min_btn = tk.Button(
            bar, text=" − ", bg="#161b22", fg="#8b949e",
            bd=0, activebackground="#30363d", activeforeground="white",
            font=("Consolas", 13), cursor="hand2",
            command=self._toggle_min,
        )
        self._min_btn.pack(side="right")

        body = tk.Frame(self, bg="#0d1117", padx=10, pady=6)
        body.pack(fill="both", expand=True)
        self._body_frame = body

        # URL 行
        url_row = tk.Frame(body, bg="#0d1117")
        url_row.pack(fill="x", pady=(0, 3))
        tk.Label(url_row, text="页面:", bg="#0d1117", fg="#768390",
                 font=("Consolas", 10), width=5, anchor="w").pack(side="left")
        self.lbl_url = tk.Label(
            url_row, text="—", bg="#0d1117", fg="#adbac7",
            font=("Consolas", 10), anchor="w", wraplength=430, justify="left",
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
        tk.Label(body, text="风控 Cookie 状态", bg="#0d1117", fg="#768390",
                 font=("Consolas", 10), anchor="w").pack(fill="x")

        self.ck_box = tk.Text(
            body, bg="#0d1117", bd=0,
            font=("Consolas", 10), state="disabled",
            wrap="word", height=len(_CK_ROWS) + 3,
            width=1,  # 由 pack fill="x" 完全控制宽度            padx=2, pady=2, cursor="arrow",
            # 像素级 tab stop：第1列100px，第2列210px，之后自然延伸
            tabs=("100", "210"),
        )
        self.ck_box.pack(fill="x", expand=True, pady=(2, 4))

        _sep(body)

        # ── 事件流 ────────────────────────────────────────────────────────────
        tk.Label(body, text="实时事件流", bg="#0d1117", fg="#768390",
                 font=("Consolas", 10), anchor="w").pack(fill="x")

        self.evt_box = tk.Text(
            body, bg="#050509", fg="#8892b0",
            font=("Consolas", 10), bd=0,
            state="disabled", wrap="word", height=12,
            padx=4, pady=4,
        )
        sb = tk.Scrollbar(body, orient="vertical",
                          command=self.evt_box.yview)
        self.evt_box.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.evt_box.pack(fill="both", expand=True)

        # 右下角拖拽缩放手柄
        grip = tk.Label(self, text="◢", bg="#161b22", fg="#444",
                        font=("Consolas", 12), cursor="size_nw_se")
        grip.place(relx=1.0, rely=1.0, anchor="se")
        grip.bind("<ButtonPress-1>",   self._rs)
        grip.bind("<B1-Motion>",       self._rm)

    # ── 拖拽移动 ──────────────────────────────────────────────────────────────
    def _ds(self, e):
        self._drag_x = e.x_root - self.winfo_x()
        self._drag_y = e.y_root - self.winfo_y()

    def _dm(self, e):
        self.geometry(f"+{e.x_root - self._drag_x}+{e.y_root - self._drag_y}")

    # ── 右下角缩放 ────────────────────────────────────────────────────────────
    def _rs(self, e):   # resize start
        self._rsz_x = e.x_root
        self._rsz_y = e.y_root
        self._rsz_w = self.winfo_width()
        self._rsz_h = self.winfo_height()

    def _rm(self, e):   # resize move
        dw = e.x_root - self._rsz_x
        dh = e.y_root - self._rsz_y
        nw = max(380, self._rsz_w + dw)
        nh = max(440, self._rsz_h + dh)
        x  = self.winfo_x()
        y  = self.winfo_y()
        self.geometry(f"{nw}x{nh}+{x}+{y}")

    # ── 最小化/还原 ──────────────────────────────────────────────────────────
    def _toggle_min(self):
        x, y = self.winfo_x(), self.winfo_y()
        if not self._minimized:
            # 记住当前高度，折叠到标题栏
            self._saved_h = self.winfo_height()
            self._saved_w = self.winfo_width()
            self._body_frame.pack_forget()
            self.geometry(f"{self._saved_w}x28+{x}+{y}")
            self.minsize(380, 28)
            self._min_btn.config(text=" □ ")
            self._minimized = True
        else:
            # 还原
            self._body_frame.pack(fill="both", expand=True)
            self.geometry(f"{self._saved_w}x{self._saved_h}+{x}+{y}")
            self.minsize(380, 440)
            self._min_btn.config(text=" − ")
            self._minimized = False

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
            self.lbl_conn.configure(text="⬤  未连接", fg="#768390")
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
        """把 _state.cookies 写入 ck_box Text 控件（带颜色 tag）。"""
        # 收集每个前缀的最新值
        matched: dict[str, str] = {}
        for name, val in _state.cookies.items():
            for prefix, *_ in _CK_ROWS:
                if name.startswith(prefix) and prefix not in matched:
                    matched[prefix] = val
                    break

        box = self.ck_box
        box.configure(state="normal")
        box.delete("1.0", "end")

        # 预定义 tag
        box.tag_configure("hdr",    foreground="#768390", font=("Consolas", 8))  # 表头灰
        box.tag_configure("name",   foreground="#adbac7", font=("Consolas", 10))  # 行标签亮灰
        box.tag_configure("green",  foreground=C_GREEN,   font=("Consolas", 10, "bold"))
        box.tag_configure("yellow", foreground=C_YELLOW,  font=("Consolas", 10, "bold"))
        box.tag_configure("red",    foreground=C_RED,     font=("Consolas", 10, "bold"))
        box.tag_configure("cyan",   foreground=C_CYAN,    font=("Consolas", 10, "bold"))
        box.tag_configure("gray",   foreground=C_GRAY,    font=("Consolas", 10))
        box.tag_configure("detail", foreground="#cdd9e5", font=("Consolas", 9))  # 详情亮白

        # 表头（用 tab 对齐）
        box.insert("end", "Cookie", "hdr")
        box.insert("end", "\t状态", "hdr")
        box.insert("end", "\t说明\n", "hdr")

        COLOR_TAG = {
            C_GREEN: "green", C_YELLOW: "yellow",
            C_RED: "red",     C_CYAN: "cyan", C_GRAY: "gray",
        }
        for prefix, label, _ in _CK_ROWS:
            val = matched.get(prefix, "")
            status, color, detail = _ck_interpret(prefix, val)
            ctag = COLOR_TAG.get(color, "gray")
            box.insert("end", label, "name")
            box.insert("end", "\t", "name")
            box.insert("end", status, ctag)
            box.insert("end", "\t", ctag)
            if detail:
                box.insert("end", detail, "detail")
            box.insert("end", "\n")

        box.configure(state="disabled")


# ─────────────────────────────────────────────────────────────────────────────
def _kpi_cell(parent, title: str, default: str, col: int):
    f = tk.Frame(parent, bg="#161b22", padx=6, pady=6, relief="flat")
    f.grid(row=0, column=col, sticky="nsew", padx=2)
    tk.Label(f, text=title, bg="#161b22", fg="#768390",
             font=("Consolas", 9), anchor="w").pack(fill="x")
    v = tk.Label(f, text=default, bg="#161b22", fg="#adbac7",
                 font=("Consolas", 11, "bold"), anchor="w", wraplength=110)
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
                                new_ck[n] = c.get("value", "")
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
    ap.add_argument("--log", type=str, default=None, metavar="FILE",
                    help="将 Gigya 登录事件写入 JSONL 文件（例: logs/risk_log.jsonl）")
    ap.add_argument("--change", type=str, default="baseline", metavar="TAG",
                    help="当前改造标签，写入日志（例: baseline / +mouse_move）")
    args = ap.parse_args()

    port = _get_port(args.port)
    print(f"[RiskOverlay] 连接 CDP port={port}")

    global _log_path, _log_change
    if args.log:
        _log_path   = args.log
        _log_change = args.change
        print(f"[RiskOverlay] 日志 -> {_log_path}  change={_log_change}")

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
