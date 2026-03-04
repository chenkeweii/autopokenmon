"""
login_logic.py —— 登录流程
职责：填写账密 → 条件性点击登录 → 错误检测 → OTP 验证码 → 利用规约同意。
"""

from __future__ import annotations

import time

from playwright.async_api import Page

import config
from exceptions import LoginError, AccountNeedsResetError
from utils.anti_bot import (
    human_click,
    human_type,
    random_action_delay,
    random_mouse_wander,
)
from utils.email_fetcher import wait_for_new_email_since
from utils.logger import get_logger

logger = get_logger(__name__)


async def login(page: Page, username: str, password: str) -> None:
    """
    执行完整的登录流程（Steps 4-8）：填表 → 点击 → OTP → 利用规约。
    成功则正常返回，失败抛出 LoginError。
    """
    # ── Step 4: 填写账密 ──────────────────────────────────────────────────────
    await page.goto(
        config.POKEMON_APPOINTMENT_URL,
        wait_until="domcontentloaded",
        timeout=config.PAGE_LOAD_TIMEOUT_MS,
    )
    logger.info("Step 4 | 已加载，当前标题: %s", await page.title())

    await random_mouse_wander(page, moves=3)
    await random_action_delay()

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
        login_btn = page.locator('#form1Button, button[type="submit"], a.loginBtn').first
        await login_btn.wait_for(state="visible", timeout=config.ELEMENT_WAIT_TIMEOUT_MS)
        # 注意：不使用 expect_navigation() context manager——
        # 若导航在 context 进入后极短时间内完成（登录失败时服务器常做 POST→302→登录页 双重跳转），
        # Playwright 会错过事件导致整个 context manager 挂起直到超时。
        # 改用 wait_for_load_state("networkidle")：等待网络请求静默（JS 渲染完成），
        # 确保登录失败时的错误框文字已经挂载到 DOM。
        await human_click(page, login_btn)
        await page.wait_for_load_state("networkidle", timeout=config.PAGE_LOAD_TIMEOUT_MS)
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

        # 如果仍在登录页，主动等待错误框出现（最多 5s）再读文字，
        # 防止 networkidle 后 JS 还未完成 DOM 注入导致读到空字符串。
        error_box = page.locator(".comErrorBox, p.error, .errorBoxMain, .errorBox")
        if "/login" in page.url:
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

        # 兜底：如果仍停留在登录页（URL 含 /login）则视为登录失败
        if "/login" in page.url:
            page_text = (await page.locator("body").inner_text())[:200]
            logger.warning("Step 4 | ✗ 登录后仍在登录页，URL=%s，页面片段: %s", page.url, page_text)
            raise LoginError(f"登录后未跳转，仍在登录页: {page.url}")

    # ── Steps 5-8: OTP 流程（可按 config 跳过）────────────────────────────────
    if not config.REQUIRE_OTP:
        logger.info("Step 5-7 | [调试] 跳过验证码流程，直接进入预约步骤")
        return

    otp_wait_since = time.time()

    # Step 5: 跳转验证码页
    logger.info("Step 5 | 跳转验证码输入页: %s", config.PASSCODE_PAGE_LOCAL_URL)
    await page.goto(
        config.PASSCODE_PAGE_LOCAL_URL,
        wait_until="load",
        timeout=config.PAGE_LOAD_TIMEOUT_MS,
    )
    logger.info("Step 5 | 验证码页已加载，标题: %s", await page.title())

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
