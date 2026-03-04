"""
appoint_logic.py —— 预约流程
职责：找到目标商品卡片 → 展开详情 → 选择单选框 → 勾选同意 → 点击「応募する」链接 → 确认弹窗。
"""

from __future__ import annotations

import time

from playwright.async_api import Page

import config
from exceptions import AppointmentError
from utils.anti_bot import (
    human_click,
    random_action_delay,
    random_mouse_wander,
)
from utils.logger import get_logger

logger = get_logger(__name__)


async def make_appointment(page: Page, username: str) -> float:
    """
    在已登录的页面上完成预约操作（Steps 9-11）。
    参数 username 仅用于日志。
    成功返回点击「応募する」的 Unix 时刻（供调用方指定过滤时间），失败抛出 AppointmentError。
    """
    target_title = config.LOTTERY_TARGET_TITLE

    # ── Step 9: 调试时加载本地页 / 找商品卡片 → 滚动 → 展开详情 ──────────
    if not config.DO_CLICK_LOGIN:
        logger.info("Step 9 | [调试] 加载本地预约页: %s", config.APPOINTMENT_LOCAL_URL)
        await page.goto(
            config.APPOINTMENT_LOCAL_URL,
            wait_until="load",
            timeout=config.PAGE_LOAD_TIMEOUT_MS,
        )
        logger.info("Step 9 | 页面已加载，标题: %s", await page.title())

    logger.info("Step 9 | 寻找目标商品：「%s」", target_title)
    item = page.locator("li").filter(
        has=page.locator(".lBox p", has_text=target_title)
    )
    await item.wait_for(state="visible", timeout=config.ELEMENT_WAIT_TIMEOUT_MS)
    logger.info("Step 9 | ✓ 找到商品卡片")

    await item.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'smooth'})")
    await random_action_delay(0.8, 1.5)
    await random_mouse_wander(page, moves=2)
    await random_action_delay()

    # 点击「詳しく見る」展开详情
    detail_btn = item.locator("dl.subDl dt")
    await detail_btn.wait_for(state="visible", timeout=config.ELEMENT_WAIT_TIMEOUT_MS)
    await human_click(page, detail_btn)
    logger.info("Step 9 | 已点击「詳しく見る」，等待内容展开...")

    # 等待单选框出现确认展开成功
    try:
        await page.wait_for_selector(
            f'input[type="radio"][aria-label*="{target_title}"]',
            state="attached",
            timeout=config.ELEMENT_WAIT_TIMEOUT_MS,
        )
    except Exception:
        raise AppointmentError(
            f"Step 9 | 商品「{target_title}」的应募单选按鈕未出现，"
            f"可能原因：(1)商品标题与页面不匹配 (2)详情内容未展开 (3)商品已下架"
        )
    logger.info("Step 9 | ✓ 展开成功")

    # ── Step 10: 单选框 + 同意复选框 ───────────────────────────────────
    logger.info("Step 10 | 寻找商品单选按鈕...")
    await random_action_delay()

    radio = page.locator(f'input[type="radio"][aria-label*="{target_title}"]')
    await radio.wait_for(state="attached", timeout=config.ELEMENT_WAIT_TIMEOUT_MS)
    await radio.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'smooth'})")
    await random_action_delay(0.5, 1.2)
    try:
        await radio.evaluate("el => el.click()")
    except Exception as e:
        raise AppointmentError(f"Step 10 | 单选框点击失败: {e}") from e
    logger.info("Step 10 | ✓ 已选择商品单选框")

    await random_action_delay(0.5, 1.0)

    form = radio.locator("xpath=ancestor::form")
    consent_cb = form.locator("input.-check")
    await consent_cb.wait_for(state="attached", timeout=config.ELEMENT_WAIT_TIMEOUT_MS)
    await consent_cb.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'smooth'})")
    await random_action_delay(0.5, 1.0)
    try:
        await consent_cb.evaluate("el => el.click()")
    except Exception as e:
        raise AppointmentError(f"Step 10 | 同意复选框点击失败: {e}") from e
    logger.info("Step 10 | ✓ 已勾选「応募要項に同意する」")

    # ── Step 11: 点击「応募する」链接 → 等待弹窗 → 点弹窗内确认按钮 ──────
    # 页面结构：勾选 checkbox 后，form 内 ul.linkList > a 变为可点击，
    # 点击该链接触发 #pop01 弹窗，弹窗内才是最终提交的 #applyBtn。
    await random_action_delay(0.5, 1.2)

    apply_link = form.locator("ul.linkList a")
    try:
        await apply_link.wait_for(state="visible", timeout=config.ELEMENT_WAIT_TIMEOUT_MS)
        await apply_link.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'smooth'})")
        await random_action_delay(0.3, 0.8)
        await human_click(page, apply_link)
        logger.info("Step 11 | 已点击「応募する」链接，等待确认弹窗...")
    except Exception as e:
        raise AppointmentError(f"Step 11 | 「応募する」链接未出现或点击失败: {e}") from e

    await random_action_delay(0.5, 1.0)
    confirm_btn = page.locator("#applyBtn")
    submit_ts = time.time()  # 点击前记录，确保点击后到达的邮件不会被漏
    try:
        await confirm_btn.wait_for(state="visible", timeout=config.ELEMENT_WAIT_TIMEOUT_MS)
        await confirm_btn.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'smooth'})")
        await random_action_delay(0.3, 0.8)
        await human_click(page, confirm_btn)
        logger.info("Step 11 | ✓ 已点击弹窗内「応募する」，预约提交完成，返回提交时刻")
    except Exception as e:
        raise AppointmentError(
            f"Step 11 | 确认弹窗未出现或点击失败: {e}"
        ) from e

    return submit_ts
