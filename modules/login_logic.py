"""
login_logic.py —— 登录流程
职责：填写账密 → 条件性点击登录 → 错误检测 → OTP 验证码 → 利用规约同意。
"""

from __future__ import annotations

import asyncio
import json as _json
import os as _os
import random
import time
from datetime import datetime as _datetime

from playwright.async_api import Page

import config
from exceptions import LoginError, AccountNeedsResetError
from utils.anti_bot import (
    human_click,
    human_type,
    page_idle_behavior,
    random_action_delay,
    random_mouse_wander,
    random_scroll,
)
from utils.anti_bot import random_scroll
from utils.email_fetcher import wait_for_new_email_since
from utils.logger import get_logger

logger = get_logger(__name__)

_RISK_LOG = "logs/risk_log.jsonl"  # 与 risk_overlay.py 共用同一文件


def _write_risk_log(url: str, data: dict, status: int) -> None:
    """Playwright 内部直接写入风控基线日志，不依赖 overlay 进程。"""
    try:
        _os.makedirs("logs", exist_ok=True)
        ra    = data.get("riskAssessment")
        score = ra.get("score") if isinstance(ra, dict) else ra
        allow = ra.get("allow") if isinstance(ra, dict) else None
        uid   = data.get("UID", "")
        entry = {
            "ts":         _datetime.now().isoformat(timespec="seconds"),
            "change":     "baseline",
            "url":        url.split("?")[0],
            "errorCode":  data.get("errorCode", "?"),
            "uid":        uid[:20] if uid else "",
            "botSuspected": data.get("isBotSuspected"),
            "riskScore":  score,
            "riskAllow":  allow,
            "httpStatus": status,
            "source":     "playwright",
            "rawKeys":    list(data.keys())[:20],
        }
        with open(_RISK_LOG, "a", encoding="utf-8") as f:
            f.write(_json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.debug("风控日志写入失败: %s", exc)


def _make_gigya_handler():
    """
    返回一个 Playwright response 监听器。
    拦截 Gigya accounts.login / accounts.tfa 等登录 API 响应，
    在页面跳转前实时记录 errorCode / riskScore / botSuspected。
    """
    def on_response(response):
        url = response.url
        is_gigya = ("gigya.com" in url or "pokemoncenter-online.com" in url)
        is_login = ("accounts.login" in url or "accounts.tfa" in url
                    or "accounts.finalizeRegistration" in url)
        if not (is_gigya and is_login):
            return

        async def _read():
            try:
                text = await response.text()
                # 支持纯 JSON 和 JSONP格式（gigya.callback_xxx({...})）
                start = text.find("{")
                end   = text.rfind("}") + 1
                if start == -1 or end <= start:
                    return
                data = _json.loads(text[start:end])
            except Exception:
                return

            err   = data.get("errorCode", "?")
            ra    = data.get("riskAssessment")
            score = ra.get("score") if isinstance(ra, dict) else ra
            allow = ra.get("allow") if isinstance(ra, dict) else None
            bot   = data.get("isBotSuspected")
            uid   = data.get("UID", "")

            logger.info(
                "✶ Gigya登录响应 | %s | errorCode=%s | riskScore=%s | allow=%s | botSuspected=%s%s",
                url.split("?")[0].rsplit("/", 1)[-1],
                err, score, allow, bot,
                f" | UID={uid[:16]}…" if uid else "",
            )
            _write_risk_log(url, data, response.status)

        asyncio.ensure_future(_read())

    return on_response


async def login(page: Page, username: str, password: str) -> None:
    """
    执行完整的登录流程（Steps 4-8）：填表 → 点击 → OTP → 利用规约。
    成功则正常返回，失败抛出 LoginError。
    """
    # ── 注册 Gigya 响应拦截器（在 goto 之前，确保不漏掉任何响应）────────────────
    _gigya_handler = _make_gigya_handler()
    page.on("response", _gigya_handler)

    # ── Step 3b: 导航路径还原（P0.3）──────────────────────────────────────────
    # 直接打开预约页会触发 302 跳转，路径异常信号极强。
    # 改为：先打开主页 → 等 Gigya 初始化 → 再打开预约页 → 自然跳转到登录页
    if config.DO_CLICK_LOGIN:
        logger.info("Step 3b | 先打开主页，建立正常导航路径...")
        try:
            await page.goto(
                config.POKEMON_HOME_URL,
                wait_until="domcontentloaded",
                timeout=config.PAGE_LOAD_TIMEOUT_MS,
            )
        except Exception as _e:
            if "ERR_ABORTED" in str(_e) or "frame was detached" in str(_e):
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
            else:
                raise

        # P0.6: 等待 Gigya SDK 初始化完成
        logger.info("Step 3b | 等待 Gigya SDK 初始化...")
        try:
            await page.wait_for_function(
                "() => window.gigya && window.gigya.isReady === true",
                timeout=15000,
            )
            logger.info("Step 3b | Gigya SDK 已就绪")
        except Exception:
            logger.warning("Step 3b | Gigya SDK 初始化等待超时，继续执行")

        # P0.2: 主页空闲行为（模拟真人浏览）
        await random_mouse_wander(page, moves=random.randint(3, 5))
        await page_idle_behavior(page)

        # 空闲浏览后滚回顶部：Pokemon Center 网站在向下滚动时通过 CSS transform
        # 将 header slide-up 到视口外。transform 隐藏不影响 Playwright visible 判断，
        # 但 bounding_box().y 会是负值 → human_click 坐标打到视口外 → 毫无反应。
        # 用瞬间滚动（不加 smooth）确保 header 立刻弹回。
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(1.5)  # 等 header slide-down 动画完成（通常 300ms，留足余量）

        # 从主页点击「ログイン ／ 会員登録」按钮（建立自然导航路径）
        # 用 :visible 自动适配 PC（ul.logList 文字链接）和 SP（ul.linkList 图标链接）两种布局
        logger.info("Step 3b | 点击主页「ログイン ／ 会員登録」按钮...")
        _login_nav = page.locator('a[href*="/login/"]:visible').first
        await _login_nav.wait_for(state="visible", timeout=config.ELEMENT_WAIT_TIMEOUT_MS)

        await _login_nav.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
        await random_action_delay(0.5, 1.0)
        # expect_navigation 必须包住点击：确保等到点击触发的导航完成后再继续
        # 不能用 wait_for_load_state（页面已加载时会立即返回，导航尚未开始）
        async with page.expect_navigation(
            wait_until="domcontentloaded",
            timeout=config.PAGE_LOAD_TIMEOUT_MS,
        ):
            await human_click(page, _login_nav)
        logger.info("Step 3b | ✓ 已跳转到登录页: %s", page.url)

    # ── Step 4: 填写账密 ──────────────────────────────────────────────────────
    # 生产模式：Step 3b 已通过点击登录按钮自然到达登录页，无需再 goto
    # 调试模式：通过 goto(POKEMON_APPOINTMENT_URL) 触发 302 重定向到登录页
    if not config.DO_CLICK_LOGIN:
        try:
            await page.goto(
                config.POKEMON_APPOINTMENT_URL,
                wait_until="domcontentloaded",
                timeout=config.PAGE_LOAD_TIMEOUT_MS,
            )
        except Exception as _nav_err:
            _nav_err_str = str(_nav_err)
            if "ERR_ABORTED" in _nav_err_str or "frame was detached" in _nav_err_str:
                logger.warning("Step 4 | 导航 ERR_ABORTED，等待页面落地后继续...")
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
            else:
                raise
    logger.info("Step 4 | 当前页面: %s | URL: %s", await page.title(), page.url)

    # P0.6: 登录页也等 Gigya 初始化（未经主页进入时 Gigya 可能未就绪）
    try:
        await page.wait_for_function(
            "() => window.gigya && window.gigya.isReady === true",
            timeout=10000,
        )
    except Exception:
        pass  # 超时则继续，不阻断流程

    # P0.2: 登录页空闲行为（让 Gigya 采集到行为基线后再操作）
    await random_mouse_wander(page, moves=3)
    await page_idle_behavior(page)

    email_input = page.locator('input[type="email"], input[name="email"], input[name="mail"]').first
    await email_input.wait_for(state="visible", timeout=config.ELEMENT_WAIT_TIMEOUT_MS)
    await human_click(page, email_input)
    await random_action_delay(0.3, 0.8)
    await human_type(page, username)
    logger.info("Step 4 | 邮箱已输入: %s", username)

    await random_action_delay(0.5, 1.2)

    pwd_input = page.locator('input[type="password"]').first
    await pwd_input.wait_for(state="visible", timeout=config.ELEMENT_WAIT_TIMEOUT_MS)
    await human_click(page, pwd_input)
    await random_action_delay(0.3, 0.8)
    await human_type(page, password)
    logger.info("Step 4 | 密码已输入完成（内容不显示）")

    await random_action_delay(0.5, 1.2)

    # ── Step 4b: 登录按钮 / 调试分支 ─────────────────────────────────────────
    if config.DO_CLICK_LOGIN:
        # 手机端：输完密码后软键盘处于弹出状态，第一次点击会被系统截走用于收起键盘
        # 先 blur 掉当前输入框焦点，等待键盘收起动画（约 300ms）后再点击登录按钮
        await page.evaluate("() => { if (document.activeElement) document.activeElement.blur(); }")
        await asyncio.sleep(0.6)  # 等键盘完全收起
        login_btn = page.locator('#form1Button, button[type="submit"], input[type="submit"], a.loginBtn').first
        try:
            await login_btn.wait_for(state="visible", timeout=config.ELEMENT_WAIT_TIMEOUT_MS)
        except Exception:
            # 诊断：打出页面所有 button/submit/loginBtn 候选元素的当前 CSS 状态
            _diag = await page.evaluate("""() => Array.from(
                document.querySelectorAll('button, input[type=submit], a[class*=login], a[class*=btn]')
            ).map(e => {
                const s = getComputedStyle(e);
                return {tag: e.tagName, id: e.id,
                        cls: e.className.substring(0, 40),
                        txt: e.textContent.trim().substring(0, 20),
                        display: s.display, visibility: s.visibility, opacity: s.opacity,
                        w: e.offsetWidth, h: e.offsetHeight};
            })""")
            logger.warning("Step 4b | 登录按钮15s未出现，页面按钮列表: %s | URL: %s",
                           str(_diag[:10]), page.url)
            raise
        # 注意：不使用 expect_navigation() context manager——
        # 若导航在 context 进入后极短时间内完成（登录失败时服务器常做 POST→302→登录页 双重跳转），
        # Playwright 会错过事件导致整个 context manager 挂起直到超时。
        # 改用 wait_for_load_state("networkidle")：等待网络请求静默（JS 渲染完成），
        # 确保登录失败时的错误框文字已经挂载到 DOM。
        # OTP 时间基准必须在点击前设置：Gigya 收到请求后立即发邮件（< 1s），
        # 若在 MFA 检测后才设 since_ts，邮件 INTERNALDATE 会早于 since_ts 被过滤掉
        otp_wait_since = time.time()

        # 点击登录按钮，最多重试 3 次
        # 手机端：键盘未完全收起时第一次点击会被系统截走（用于关闭键盘），页面不会有任何响应
        # 判断依据：点击后 3s 内 URL 未发生任何变化 → 说明表单根本没有提交 → 重试
        for _click_attempt in range(3):
            if _click_attempt > 0:
                logger.warning(
                    "Step 4b | 点击后 3s 页面无响应，疑似被手机键盘截走，第 %d 次重试...",
                    _click_attempt + 1,
                )
                await page.evaluate("() => { if (document.activeElement) document.activeElement.blur(); }")
                await asyncio.sleep(0.8)

            _url_before = page.url
            await human_click(page, login_btn)

            # 等待 URL 变化（表单已提交），3s 超时
            try:
                await page.wait_for_function(
                    f"() => location.href !== {repr(_url_before)}",
                    timeout=3000,
                )
                logger.info("Step 4b | ✓ 第 %d 次点击生效，页面开始响应", _click_attempt + 1)
                break  # URL 变了，点击成效
            except Exception:
                if _click_attempt == 2:
                    logger.warning("Step 4b | 3 次点击均未触发页面跳转，继续等待后续检测...")

        # wait_for_load_state("networkidle") 在有大量 Analytics/GTM 追踪请求的页面
        # 永远不会触发（60s 超时）。改为等 "load" + 短暂固定等待，确保 Gigya
        # 回包后 DOM 错误框已渲染。Gigya 响应早于 page load，DOM 注入通常在 1~2s 内完成。
        try:
            await page.wait_for_load_state("load", timeout=30000)
        except Exception:
            pass  # load 超时也继续，Gigya 响应通过 response 拦截器已捕获
        await asyncio.sleep(2)  # 等 Gigya 注入错误框 / 完成页面跳转
        logger.info("Step 4 | 页面跳转完成，检查登录结果...")

    elif config.SIMULATE_LOGIN_ERROR_PAGE:
        logger.info(
            "Step 4 | [调试] 加载登录报错页 (编号%d): %s",
            config.LOGIN_ERROR_TEST_NUM,
            config.LOGIN_ERROR_TEST_URL,
        )
        await page.goto(
            config.LOGIN_ERROR_TEST_URL,
            wait_until="load",
            timeout=config.PAGE_LOAD_TIMEOUT_MS,
        )

    else:
        logger.info("Step 4 | [调试] 不点击登录，直接往后续步骤执行")

    # ── 登录错误检测 ──────────────────────────────────────────────────────────
    if config.DO_CLICK_LOGIN or config.SIMULATE_LOGIN_ERROR_PAGE:
        # 先记录当前 URL / 标题，便于调试
        logger.info("Step 4 | 当前 URL: %s | 标题: %s", page.url, await page.title())

        # ── MFA 检测：login-mfa.html = 账号开启了邮箱验证码 ──────────────────────
        # 注意：不要落入下面的「仍在登录页」判断，/login-mfa 含 /login 会误报
        if "login-mfa" in page.url:
            if not config.REQUIRE_OTP:
                logger.warning(
                    "Step 4 | 账号 %s 开启了 MFA，REQUIRE_OTP=False 无法处理: %s",
                    username, page.url,
                )
                raise LoginError(f"MFA_REQUIRED:{page.url}")
            logger.info(
                "Step 4 | 账号 %s 进入 MFA 验证页，继续 OTP 流程: %s",
                username, page.url,
            )

        # 如果仍在登录页，主动等待错误框出现（最多 5s）再读文字，
        # 防止 networkidle 后 JS 还未完成 DOM 注入导致读到空字符串。
        error_box = page.locator(".comErrorBox, p.error, .errorBoxMain, .errorBox")
        # MFA 页不需要等错误框（登录本身已通过），只在普通登录失败页等待
        if "/login" in page.url and "login-mfa" not in page.url:
            try:
                await error_box.first.wait_for(state="visible", timeout=5000)
            except Exception:
                pass  # 5s 内没出现错误框，继续后续兜底判断

        if await error_box.count() > 0:
            error_text = (await error_box.first.inner_text()).strip()
            logger.warning("Step 4 | ✗ 登录失败，错误信息: 「%s」", error_text)
            # 「エラーが発生しました。時間をおいてから再度お試しください。」= 账号需重置密码，与 IP 无关，单独抛出
            if "エラーが発生しました" in error_text:
                raise AccountNeedsResetError(error_text)
            raise LoginError(error_text)

        # 兜底：如果仍停留在登录页（URL 含 /login，且不是 MFA 页）则视为登录失败
        if "/login" in page.url and "login-mfa" not in page.url:
            page_text = (await page.locator("body").inner_text())[:200]
            logger.warning("Step 4 | ✗ 登录后仍在登录页，URL=%s，页面片段: %s", page.url, page_text)
            raise LoginError(f"登录后未跳转，仍在登录页: {page.url}")

    # ── Steps 5-8: OTP 流程（可按 config 跳过）────────────────────────────────
    if not config.REQUIRE_OTP:
        logger.info("Step 5-7 | [调试] 跳过验证码流程，直接进入预约步骤")
        return

    # otp_wait_since 已在点击登录按钮前设置（DO_CLICK_LOGIN=True 时）
    # 调试路径（DO_CLICK_LOGIN=False）没有点击动作，在此兜底设置
    if "otp_wait_since" not in locals():
        otp_wait_since = time.time()

    # Step 5: 跳转验证码页
    # 生产环境：登录后浏览器已在真实 MFA 页（login-mfa.html），直接跳过 goto
    # 调试模式：DO_CLICK_LOGIN=False 时跳转本地测试页
    if "login-mfa" in page.url:
        logger.info("Step 5 | 已在 MFA 验证页（生产），跳过页面跳转: %s", page.url)
    else:
        logger.info("Step 5 | 跳转验证码输入页: %s", config.PASSCODE_PAGE_LOCAL_URL)
        await page.goto(
            config.PASSCODE_PAGE_LOCAL_URL,
            wait_until="load",
            timeout=config.PAGE_LOAD_TIMEOUT_MS,
        )
    logger.info("Step 5 | 验证码页就绪，标题: %s | URL: %s", await page.title(), page.url)

    # Step 6: 等待 OTP 邮件
    logger.info("Step 6 | 等待验证码邮件（最多 %d 秒）...", config.EMAIL_OTP_WAIT)
    mail = await wait_for_new_email_since(
        since_ts=otp_wait_since,
        timeout_seconds=config.EMAIL_OTP_WAIT,
        recipient=username,
    )
    if not mail:
        raise LoginError("Step 6 | 超时未收到验证码邮件")

    otp_code = mail["otp_code"]
    logger.info(
        "Step 6 | ✓ 收到验证码邮件 → otp: %s | received: %s",
        otp_code, mail["original_received_at"],
    )

    # Step 7: 填入 OTP，点击确认
    await random_mouse_wander(page, moves=2)
    await random_action_delay()

    otp_input = page.locator("#authCode")
    await otp_input.wait_for(state="visible", timeout=config.ELEMENT_WAIT_TIMEOUT_MS)
    await human_click(page, otp_input)
    await random_action_delay(0.3, 0.6)
    await human_type(page, otp_code)
    logger.info("Step 7 | 验证码已填入: %s", otp_code)

    await random_action_delay(0.5, 1.0)

    auth_btn = page.locator("#authBtn")
    await auth_btn.wait_for(state="visible", timeout=config.ELEMENT_WAIT_TIMEOUT_MS)
    await human_click(page, auth_btn)
    logger.info("Step 7 | ✓ 已点击「認証する」，等待页面跳转...")

    if config.SIMULATE_TERMS_PAGE:
        logger.info("Step 7 | [调试] 模拟跳转到利用规约再同意页")
        await page.goto(
            config.TERMS_PAGE_LOCAL_URL,
            wait_until="load",
            timeout=config.PAGE_LOAD_TIMEOUT_MS,
        )
    else:
        await page.wait_for_load_state("domcontentloaded", timeout=config.PAGE_LOAD_TIMEOUT_MS)

    logger.info("Step 7 | 当前页面标题: %s", await page.title())

    # Step 8: 利用规约再同意页
    is_terms_page = await page.locator("#terms").count() > 0
    if is_terms_page:
        logger.info("Step 8 | 检测到利用规约再同意页，开始勾选复选框...")
        await random_action_delay()

        terms_label = page.locator("label[for='terms']")
        await terms_label.wait_for(state="visible", timeout=config.ELEMENT_WAIT_TIMEOUT_MS)
        await terms_label.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'smooth'})")
        await random_action_delay(0.4, 0.8)
        await human_click(page, terms_label)

        await random_action_delay(0.3, 0.8)

        privacy_label = page.locator("label[for='privacyPolicy']")
        await privacy_label.wait_for(state="visible", timeout=config.ELEMENT_WAIT_TIMEOUT_MS)
        await privacy_label.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'smooth'})")
        await random_action_delay(0.3, 0.7)
        await human_click(page, privacy_label)
        logger.info("Step 8 | ✓ 已勾选两个复选框")

        await random_action_delay(0.5, 1.0)

        next_btn = page.locator("#termsApplyBtn")
        await next_btn.wait_for(state="visible", timeout=config.ELEMENT_WAIT_TIMEOUT_MS)
        await human_click(page, next_btn)
        logger.info("Step 8 | ✓ 已点击「次へ進む」")

        await page.wait_for_load_state("domcontentloaded", timeout=config.PAGE_LOAD_TIMEOUT_MS)
        logger.info("Step 8 | 当前页面标题: %s", await page.title())
    else:
        logger.info("Step 8 | 无利用规约页，登录流程完成")

    # ── 注销 Gigya 响应拦截器 ─────────────────────────────────────────────────
    page.remove_listener("response", _gigya_handler)


async def navigate_to_lottery(page: Page, username: str, password: str) -> None:
    """
    Step 9b: 登录后从マイページ导航到抽选应募一览页（lottery/apply.html）。

    完整路径：
      マイページ
        → 点击「抽選履歴」标签
        → 等出现并点击「抽選履歴一覧を見る」
        → 抽選申込み履歴页：点击含 alt=「開催中の抽選一覧」的图片
        → 抽選応募方法紹介页：向下滚动，点击「抽選へ進む」(a.goLotteryBtn)
        → 抽選応募一覧（apply.html）
          ↳ 若触发二次登录，自动重新填写账密+OTP 再进入

    调试模式（DO_CLICK_LOGIN=False）：直接返回，不导航（make_appointment 会加载本地测试页）。
    """
    if not config.DO_CLICK_LOGIN:
        logger.info("Step 9b | [调试] 跳过导航流程")
        return

    logger.info("Step 9b | 开始导航：マイページ → 抽选応募一覧")

    # ── Step 9b-0: 确保当前在 マイページ ─────────────────────────────────────
    if "mypage" not in page.url.lower():
        logger.info("Step 9b-0 | 当前 URL=%s，直接跳转到 マイページ...", page.url)
        await page.goto(
            config.MYPAGE_URL,
            wait_until="domcontentloaded",
            timeout=config.PAGE_LOAD_TIMEOUT_MS,
        )
    await random_action_delay(1.0, 2.0)
    await random_mouse_wander(page, moves=random.randint(2, 4))
    logger.info("Step 9b-0 | ✓ 当前在 マイページ: %s", page.url)

    # ── Step 9b-1: 点击「抽選履歴」标签 ──────────────────────────────────────
    logger.info("Step 9b-1 | 点击「抽選履歴」标签...")
    chuju_tab = page.locator('a:has-text("抽選履歴")').first
    await chuju_tab.wait_for(state="visible", timeout=config.ELEMENT_WAIT_TIMEOUT_MS)
    await chuju_tab.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'smooth'})")
    await random_action_delay(0.5, 1.0)
    await human_click(page, chuju_tab)
    logger.info("Step 9b-1 | ✓ 已点击「抽選履歴」标签")

    # ── Step 9b-2: 等待并点击「抽選履歴一覧を見る」─────────────────────────
    logger.info("Step 9b-2 | 等待并点击「抽選履歴一覧を見る」...")
    history_link = page.locator('a:has-text("抽選履歴一覧を見る")').first
    await history_link.wait_for(state="visible", timeout=config.ELEMENT_WAIT_TIMEOUT_MS)
    await random_action_delay(0.5, 1.2)
    await human_click(page, history_link)
    await page.wait_for_load_state("domcontentloaded", timeout=config.PAGE_LOAD_TIMEOUT_MS)
    logger.info("Step 9b-2 | ✓ 到达抽奖历史一览页: %s", page.url)

    await random_mouse_wander(page, moves=2)
    await page_idle_behavior(page)

    # ── Step 9b-3: 点击「開催中の抽選一覧」图片（进入抽奖介绍页）─────────────
    logger.info("Step 9b-3 | 寻找并点击「開催中の抽選一覧」图片...")
    # HTML: <a href="/lottery/landing-page.html"><img alt="開催中の抽選一覧"></a>
    banner_link = page.locator('a:has(img[alt="開催中の抽選一覧"])').first
    await banner_link.wait_for(state="visible", timeout=config.ELEMENT_WAIT_TIMEOUT_MS)
    await banner_link.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'smooth'})")
    await random_action_delay(0.5, 1.0)
    await human_click(page, banner_link)
    await page.wait_for_load_state("domcontentloaded", timeout=config.PAGE_LOAD_TIMEOUT_MS)
    logger.info("Step 9b-3 | ✓ 到达抽奖介绍页: %s", page.url)

    await random_mouse_wander(page, moves=random.randint(2, 4))
    await random_action_delay(0.8, 1.5)

    # ── Step 9b-4: 向下滚动，点击底部「抽選へ進む」（a.goLotteryBtn）──────────
    logger.info("Step 9b-4 | 向下滚动，点击「抽選へ進む」...")
    await random_scroll(page, times=3)
    await random_action_delay(0.5, 1.0)

    # class="goLotteryBtn" 是页面底部的大按钮，比 #step3Btn 更靠下符合人类操作习惯
    go_btn = page.locator('a.goLotteryBtn').first
    if await go_btn.count() == 0:
        go_btn = page.locator('a:has-text("抽選へ進む")').last
    await go_btn.wait_for(state="visible", timeout=config.ELEMENT_WAIT_TIMEOUT_MS)
    await go_btn.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'smooth'})")
    await random_action_delay(0.5, 1.0)
    await human_click(page, go_btn)
    await page.wait_for_load_state("domcontentloaded", timeout=config.PAGE_LOAD_TIMEOUT_MS)
    logger.info("Step 9b-4 | ✓ 已点击「抽選へ進む」，当前 URL: %s", page.url)

    # ── Step 9b-5: 处理可能的二次登录 ────────────────────────────────────────
    # apply.html 风控比主页严格，有时会触发二次登录检查（跳转到 /login/）
    if "/login" in page.url and "login-mfa" not in page.url:
        logger.info("Step 9b-5 | 检测到二次登录要求，重新填写账密...")
        # 等待 Gigya 初始化
        try:
            await page.wait_for_function(
                "() => window.gigya && window.gigya.isReady === true",
                timeout=10000,
            )
        except Exception:
            pass
        await random_mouse_wander(page, moves=2)
        await random_action_delay(1.0, 2.0)

        _em = page.locator('input[type="email"], input[name="email"], input[name="mail"]').first
        await _em.wait_for(state="visible", timeout=config.ELEMENT_WAIT_TIMEOUT_MS)
        await human_click(page, _em)
        await random_action_delay(0.3, 0.8)
        await human_type(page, username)

        await random_action_delay(0.5, 1.2)
        _pw = page.locator('input[type="password"]').first
        await _pw.wait_for(state="visible", timeout=config.ELEMENT_WAIT_TIMEOUT_MS)
        await human_click(page, _pw)
        await random_action_delay(0.3, 0.8)
        await human_type(page, password)

        await random_action_delay(0.5, 1.2)
        _btn = page.locator('#form1Button, button[type="submit"], a.loginBtn').first
        await _btn.wait_for(state="visible", timeout=config.ELEMENT_WAIT_TIMEOUT_MS)
        await human_click(page, _btn)
        await page.wait_for_load_state("networkidle", timeout=config.PAGE_LOAD_TIMEOUT_MS)

        # 错误检测
        _err = page.locator(".comErrorBox, p.error, .errorBoxMain, .errorBox")
        if await _err.count() > 0:
            _err_txt = (await _err.first.inner_text()).strip()
            raise LoginError(f"二次登录失败: {_err_txt}")

        # 二次登录也可能触发 MFA（少见，但防御性处理）
        if "login-mfa" in page.url and config.REQUIRE_OTP:
            logger.info("Step 9b-5 | 二次登录触发 OTP，处理中...")
            _otp_since = time.time()
            _mail = await wait_for_new_email_since(
                since_ts=_otp_since,
                timeout_seconds=config.EMAIL_OTP_WAIT,
                recipient=username,
            )
            if not _mail:
                raise LoginError("Step 9b-5 | 二次登录 OTP 超时未收到邮件")
            _otp = _mail["otp_code"]
            _otp_inp = page.locator("#authCode")
            await _otp_inp.wait_for(state="visible", timeout=config.ELEMENT_WAIT_TIMEOUT_MS)
            await human_click(page, _otp_inp)
            await human_type(page, _otp)
            _auth_btn = page.locator("#authBtn")
            await human_click(page, _auth_btn)
            await page.wait_for_load_state("domcontentloaded", timeout=config.PAGE_LOAD_TIMEOUT_MS)

        logger.info("Step 9b-5 | ✓ 二次登录完成，当前 URL: %s", page.url)

    logger.info("Step 9b | ✓ 导航完成，现在位于: %s", page.url)
