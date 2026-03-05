"""
monitor_risk.py —— 风控状态监控工具（独立运行，不影响主流程）

用途：连接已运行的 Nstbrowser，在页面加载和登录过程中，
      静默拦截 Gigya / Treasure Data 的所有请求与响应，
      输出风控评分、账号状态、错误码等原始数据。

使用方式：
    python monitor_risk.py                    # 自动连接第一个运行中的浏览器
    python monitor_risk.py --port 23511       # 指定 CDP 端口
    python monitor_risk.py --email x@x.com --password xxx   # 同时测试登录
    python monitor_risk.py --help
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

# ── 路径修正（嵌入式 Python / 直接运行均适用）────────────────────────────────
_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)
os.chdir(_DIR)
if hasattr(os, "add_dll_directory"):
    _py = os.path.join(_DIR, "python")
    if os.path.isdir(_py):
        os.add_dll_directory(_py)

import requests as _requests
from playwright.async_api import async_playwright, Response, Request

import config

# ── ANSI 颜色 ─────────────────────────────────────────────────────────────────
_R  = "\033[0m"
_BOLD = "\033[1m"
_GREEN  = "\033[92m"
_YELLOW = "\033[93m"
_RED    = "\033[91m"
_CYAN   = "\033[96m"
_GRAY   = "\033[90m"
_BLUE   = "\033[94m"

def _c(color, text): return f"{color}{text}{_R}"

# ── 目标域名 / 关键字 ─────────────────────────────────────────────────────────
WATCH_DOMAINS = (
    "gigya.com",
    "cdns.gigya.com",
    "id.pokemoncenter-online.com",   # Gigya IDS 托管端点（accounts.login 在此）
    "treasuredata.com",
    "collect.igodigital.com",
    "cquotient.com",
    "pokemoncenter-online.com",      # 直接监听登录请求
)

# Gigya errorCode 含义表
GIGYA_ERROR_CODES = {
    0:       (_GREEN,  "成功 / 评分通过"),
    200001:  (_YELLOW, "请求参数缺失"),
    400006:  (_YELLOW, "需要额外身份验证"),
    401001:  (_RED,    "未授权"),
    401002:  (_RED,    "密码错误"),
    401003:  (_RED,    "登录失败（通用）"),
    401022:  (_YELLOW, "⚠️  账号待重置密码（非风控）"),
    403010:  (_RED,    "reCAPTCHA 验证失败"),
    403100:  (_RED,    "账号被封禁"),
    403102:  (_RED,    "⚠️  设备/IP 被风控拦截（评分过低）"),
    403047:  (_RED,    "账号临时锁定"),
    408001:  (_YELLOW, "请求超时"),
    500001:  (_RED,    "服务器内部错误"),
}

# ─────────────────────────────────────────────────────────────────────────────
class RiskMonitor:
    def __init__(self):
        self.captured: list[dict] = []   # 所有拦截到的条目
        self._req_map: dict[str, float] = {}  # request id → 发起时间

    def _label_url(self, url: str) -> str:
        """给 URL 打上来源标签"""
        # id.pokemoncenter-online.com/accounts.* 是 Gigya IDS 托管端点
        if "id.pokemoncenter-online.com" in url:
            if "accounts.login"           in url: return "Gigya·login"
            if "accounts.getAccountInfo"  in url: return "Gigya·getInfo"
            if "accounts.tfa"             in url: return "Gigya·tfa"
            if "accounts."               in url: return "Gigya·IDS"
            if "sdk.config"              in url: return "Gigya·sdk"
            return "Gigya·IDS"
        if "gigya" in url:
            if "accounts.login"      in url: return "Gigya·login"
            if "accounts.initRegistration" in url: return "Gigya·initReg"
            if "accounts.getAccountInfo"   in url: return "Gigya·getInfo"
            if "accounts.getRiskAssessment" in url: return "Gigya·risk"
            if "socialize"           in url: return "Gigya·socialize"
            if "ids."                in url: return "Gigya·IDS"
            if "bootloader"          in url or "bootstrap" in url: return "Gigya·bootstrap"
            return "Gigya"
        if "pokemoncenter-online.com" in url:
            if "login" in url: return "Pokemon·login"
            if "lottery" in url: return "Pokemon·lottery"
            return "Pokemon"
        if "treasuredata" in url or "igodigital" in url:
            return "TreasureData"
        if "cquotient" in url:
            return "Salesforce·CQ"
        return "OTHER"

    def attach(self, page):
        """挂载请求/响应拦截器到 page"""
        page.on("request",  self._on_request)
        page.on("response", self._on_response)

    def _on_request(self, req: Request):
        for d in WATCH_DOMAINS:
            if d in req.url:
                self._req_map[req.url] = time.time()
                break

    async def _on_response(self, resp: Response):
        url = resp.url
        matched = any(d in url for d in WATCH_DOMAINS)
        if not matched:
            return

        label   = self._label_url(url)
        latency = None
        if url in self._req_map:
            latency = (time.time() - self._req_map.pop(url)) * 1000

        entry = {
            "label":   label,
            "url":     url,
            "status":  resp.status,
            "latency": latency,
            "body":    None,
            "parsed":  {},
        }

        # 尝试解析响应体
        try:
            ct = resp.headers.get("content-type", "")
            if "json" in ct or "javascript" in ct:
                raw = await resp.text()
                # Gigya 有时返回 JSONP：callback({...})
                if raw.strip().startswith("{"):
                    entry["body"] = raw[:2000]
                    entry["parsed"] = json.loads(raw)
                else:
                    # 去掉 JSONP 包装
                    start = raw.find("{")
                    end   = raw.rfind("}") + 1
                    if start != -1 and end > start:
                        inner = raw[start:end]
                        entry["body"] = inner[:2000]
                        entry["parsed"] = json.loads(inner)
        except Exception:
            pass

        self.captured.append(entry)
        # 实时打印关键事件
        self._print_entry(entry)

    def _print_entry(self, e: dict):
        label   = e["label"]
        status  = e["status"]
        latency = f"{e['latency']:.0f}ms" if e["latency"] else "?"
        p       = e["parsed"]

        # TreasureData / Salesforce / Gigya SDK 静默
        if "TreasureData" in label or "Salesforce" in label or label in ("Gigya·sdk", "Gigya·bootstrap"):
            print(_c(_GRAY, f"  [{label}] HTTP {status}  {latency}  {e['url'][:80]}"))
            return

        # Pokemon 域名：打印 URL 和状态码（观察登录跳转）
        if "Pokemon" in label:
            print(_c(_BLUE, f"  [{label}] HTTP {status}  {latency}  {e['url'][:100]}"))
            return

        # Gigya 详细
        err_code = p.get("errorCode", p.get("statusCode", "?"))
        err_msg  = p.get("errorMessage") or p.get("statusReason") or ""

        color, meaning = GIGYA_ERROR_CODES.get(err_code, (_YELLOW, "未知错误码"))
        risk = p.get("riskAssessment")
        bot_flag = p.get("isBotSuspected")
        tfa_flag = p.get("isTFASuspected")

        line = (
            f"  [{_c(_CYAN, label)}] "
            f"HTTP {status}  {latency}  "
            f"errorCode={_c(color, str(err_code))}（{meaning}）"
        )
        if err_msg:
            line += f"  msg={err_msg}"
        print(line)

        if risk is not None:
            print(f"      riskAssessment  = {_c(_YELLOW, str(risk))}")
        if bot_flag is not None:
            flag_color = _RED if bot_flag else _GREEN
            print(f"      isBotSuspected  = {_c(flag_color, str(bot_flag))}")
        if tfa_flag is not None:
            print(f"      isTFASuspected  = {str(tfa_flag)}")

        # 登录相关额外字段
        if "login" in e["url"].lower() or "accounts.login" in e["url"]:
            uid = p.get("UID") or p.get("uid")
            if uid:
                print(f"      UID             = {_c(_GREEN, uid[:20])}...（登录成功）")
            # 打印完整 parsed（仅前 600 字符）
            raw_str = json.dumps(p, ensure_ascii=False)
            if len(raw_str) > 600:
                raw_str = raw_str[:600] + "..."
            print(_c(_GRAY, f"      full: {raw_str}"))

    def print_summary(self, cookies: list[dict]):
        print()
        print(_c(_BOLD, "=" * 60))
        print(_c(_BOLD, " 汇总报告"))
        print(_c(_BOLD, "=" * 60))

        # Gigya 条目
        gigya_entries = [e for e in self.captured if "Gigya" in e["label"]]
        print(f"\n{_c(_CYAN, '▸ Gigya 请求共')} {len(gigya_entries)} 条")
        for e in gigya_entries:
            p = e["parsed"]
            err_code = p.get("errorCode", "?")
            color, meaning = GIGYA_ERROR_CODES.get(err_code, (_YELLOW, "未知"))
            print(f"   {e['label']:<22} errorCode={_c(color, str(err_code))}  {meaning}")

        # 风控关键 Cookies
        risk_cookies = {
            c["name"]: c["value"][:40]
            for c in cookies
            if any(k in c["name"] for k in (
                "gig_bootstrap", "gig_hasSession", "hoPvmDpa",
                "ktlvDW7IG5ClOcxYTbmY", "dwanonymous", "sid",
                "_td", "__cq_uuid",
            ))
        }
        print(f"\n{_c(_CYAN, '▸ 风控相关 Cookie')} {len(risk_cookies)} 个")
        for name, val in risk_cookies.items():
            exists_color = _GREEN if val else _RED
            print(f"   {_c(exists_color, '✔' if val else '✘')}  {name:<45} = {val[:30]}")

        # 结论
        print(f"\n{_c(_BOLD, '▸ 综合判断')}")
        login_entries = [e for e in gigya_entries if "login" in e["url"].lower()]
        if login_entries:
            last = login_entries[-1]
            err = last["parsed"].get("errorCode", -1)
            if err == 0:
                print(f"   {_c(_GREEN, '✔ 登录成功，风控评分通过')}")
            elif err == 403102:
                print(f"   {_c(_RED, '✘ 风控拦截（403102）：设备/IP 评分过低，不允许登录')}")
            elif err == 401002:
                print(f"   {_c(_YELLOW, '△ 密码错误（401002）：账号问题，非风控')}")
            elif err == 401022:
                print(f"   {_c(_YELLOW, '△ 账号待重置密码（401022）：非风控，该账号需在网站重置密码后再用')}")
            else:
                color, meaning = GIGYA_ERROR_CODES.get(err, (_YELLOW, "未知"))
                print(f"   {_c(color, f'△ errorCode={err}：{meaning}')}")
        elif not gigya_entries:
            print(f"   {_c(_YELLOW, '? 未捕获到任何 Gigya 请求，页面可能未完全加载')}")
        else:
            # 有 Gigya 初始化请求，但没有 accounts.login
            print(f"   {_c(_YELLOW, '? 没有捕获到 accounts.login 请求')}")
            print(f"   {_c(_GRAY, '   可能原因：表单未提交（输入事件没有触发表单验证）/ 还在登录页（风控拦截）')}")

        print()


# ── 获取第一个运行中的浏览器端口 ─────────────────────────────────────────────
def get_running_browser_endpoint(port: int | None = None) -> str:
    if port:
        return f"http://127.0.0.1:{port}"

    try:
        resp = _requests.get(
            f"http://{config.NST_HOST}/api/v2/browsers/running",
            headers={"x-api-key": config.NST_API_KEY},
            timeout=5,
        )
        data = resp.json()
        browsers = data.get("data", {}).get("list") or data.get("data") or []
        if isinstance(browsers, list) and browsers:
            b = browsers[0]
            p = b.get("port") or b.get("debugPort")
            pid = b.get("id") or b.get("profileId") or "unknown"
            if p:
                print(_c(_CYAN, f"自动选择运行中浏览器: {pid}  port={p}"))
                return f"http://127.0.0.1:{p}"
    except Exception as e:
        print(_c(_YELLOW, f"查询运行中浏览器失败: {e}"))

    # 回退：尝试默认端口
    print(_c(_YELLOW, "未找到运行中浏览器，尝试默认端口 23511"))
    return "http://127.0.0.1:23511"


# ── 主流程 ────────────────────────────────────────────────────────────────────
async def run(endpoint: str, email: str | None, password: str | None, pause: bool):
    monitor = RiskMonitor()

    print()
    print(_c(_BOLD, "=" * 60))
    print(_c(_BOLD, "  AutoPokemon 风控监控工具"))
    print(_c(_BOLD, "=" * 60))
    print(f"  CDP 端点 : {endpoint}")
    print(f"  目标页面 : {config.POKEMON_APPOINTMENT_URL}")
    if email:
        print(f"  测试账号 : {email}")
    print()

    async with async_playwright() as pw:
        print(_c(_CYAN, "▸ 连接浏览器..."))
        browser = await pw.chromium.connect_over_cdp(endpoint)

        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        # 挂载监控
        monitor.attach(page)

        # ── 1. 加载页面（观察初始化请求）───────────────────────────────────
        print(_c(_CYAN, f"▸ 加载页面: {config.POKEMON_APPOINTMENT_URL}"))
        try:
            await page.goto(
                config.POKEMON_APPOINTMENT_URL,
                wait_until="domcontentloaded",
                timeout=30000,
            )
        except Exception as e:
            if "ERR_ABORTED" in str(e) or "frame was detached" in str(e):
                print(_c(_YELLOW, "  导航 ERR_ABORTED（302跳转），等待落地..."))
                await asyncio.sleep(2)
            else:
                print(_c(_RED, f"  导航失败: {e}"))

        print(_c(_CYAN, f"▸ 等待 networkidle（Gigya 初始化）..."))
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass  # 超时也继续

        current_url = page.url
        print(f"  当前 URL : {current_url}")
        try:
            print(f"  页面标题 : {await page.title()}")
        except Exception:
            print("  页面标题 : （获取中，页面正在跳转）")
        # 如果跳转到了登录页，再等一次 networkidle 确保表单渲染完毕
        if "/login" in page.url or page.url != config.POKEMON_APPOINTMENT_URL:
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
                print(f"  跳转后 URL : {page.url}")
            except Exception:
                pass
        print()

        # ── 2. 可选：执行登录测试 ──────────────────────────────────────────
        if email and password:
            print(_c(_CYAN, "▸ 开始登录测试..."))
            try:
                # 若还未进入登录页则先等跳转
                if "/login" not in page.url:
                    try:
                        await page.wait_for_url("**/login**", timeout=8000)
                    except Exception:
                        pass
                print(f"  登录页 URL : {page.url}")

                # 等输入框出现
                email_input = page.locator(
                    'input[type="email"], input[name="email"], input[name="mail"]'
                ).first
                await email_input.wait_for(state="visible", timeout=10000)

                await email_input.click()
                await asyncio.sleep(0.5)
                # 用 type 而非 fill，触发完整 input/change 事件，表单验证才会正常识别
                await email_input.press_sequentially(email, delay=80)
                await asyncio.sleep(0.8)

                pwd_input = page.locator('input[type="password"]').first
                await pwd_input.wait_for(state="visible", timeout=5000)
                await pwd_input.click()
                await asyncio.sleep(0.5)
                await pwd_input.press_sequentially(password, delay=80)
                await asyncio.sleep(1.0)

                # 点击登录
                btn = page.locator('#form1Button, button[type="submit"], a.loginBtn').first
                await btn.click()
                print(_c(_CYAN, "▸ 已点击登录，等待响应..."))

                # 等待页面跳转或错误出现（最多 25s）
                try:
                    await page.wait_for_load_state("networkidle", timeout=25000)
                except Exception:
                    pass  # 超时也继续，读取已捕获的数据

                try:
                    print(f"  登录后 URL   : {page.url}")
                    print(f"  登录后标题   : {await page.title()}")
                except Exception:
                    pass

            except Exception as e:
                print(_c(_RED, f"  登录操作异常: {e}"))

        else:
            # 无登录测试，再等 3 秒确保初始化请求都捕捉到
            print(_c(_GRAY, "  (未指定账号，仅观察页面初始化，3s 后输出报告)"))
            await asyncio.sleep(3)

        # ── 3. 读取 Cookies ────────────────────────────────────────────────
        cookies = await ctx.cookies()

        # ── 4. 汇总报告 ────────────────────────────────────────────────────
        monitor.print_summary(cookies)

        if pause:
            print(_c(_GRAY, "（按 Enter 退出，浏览器保持打开）"))
            await asyncio.get_event_loop().run_in_executor(None, input)


# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="AutoPokemon 风控监控工具 —— 静默拦截 Gigya/TD 响应输出评分"
    )
    parser.add_argument("--port",     type=int,   default=None, help="CDP 端口（默认自动检测）")
    parser.add_argument("--email",    type=str,   default=None, help="测试登录的邮箱")
    parser.add_argument("--password", type=str,   default=None, help="测试登录的密码")
    parser.add_argument("--no-pause", action="store_true",      help="报告后直接退出，不等待 Enter")
    args = parser.parse_args()

    endpoint = get_running_browser_endpoint(args.port)

    asyncio.run(run(
        endpoint  = endpoint,
        email     = args.email,
        password  = args.password,
        pause     = not args.no_pause,
    ))


if __name__ == "__main__":
    main()
