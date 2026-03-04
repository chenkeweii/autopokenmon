"""
anti_bot.py —— 人类行为仿真工具集
职责：提供所有「让自动化看起来像人类」的原子操作。
      其他模块只需调用此处的函数，无需关心随机化细节。
"""

from __future__ import annotations

import asyncio
import random

from playwright.async_api import Page, Locator

import config
from utils.logger import get_logger

logger = get_logger(__name__)


# ───────────────────────── 随机延迟 ─────────────────────────


async def random_action_delay(
    low: float | None = None,
    high: float | None = None,
):
    """两次业务操作之间随机等待，模拟人类思考/阅读时间。"""
    lo = low  if low  is not None else config.ACTION_INTERVAL_RANGE[0]
    hi = high if high is not None else config.ACTION_INTERVAL_RANGE[1]
    await asyncio.sleep(random.uniform(lo, hi))


# ───────────────────────── 鼠标行为 ─────────────────────────


async def random_mouse_wander(page: Page, moves: int = 3):
    """
    在页面可视区域内随机移动鼠标若干次，
    模拟人类浏览页面时的无目的性移动。
    """
    viewport = page.viewport_size or {"width": 1280, "height": 720}
    for _ in range(moves):
        x = random.randint(50, viewport["width"] - 50)
        y = random.randint(50, viewport["height"] - 50)
        steps = random.randint(*config.MOUSE_MOVE_STEPS_RANGE)
        await page.mouse.move(x, y, steps=steps)
        await asyncio.sleep(random.uniform(*config.MOUSE_WANDER_PAUSE_RANGE))


async def human_click(page: Page, locator: Locator):
    """
    模拟人类点击：
    1. 获取元素中心坐标
    2. 鼠标缓慢移动到目标（带随机偏移 + 分段抖动，避免完美直线）
    3. 随机按压时长（mousedown → 短暂停顿 → mouseup），模拟真实手指按键节奏
    """
    box = await locator.bounding_box()
    if not box:
        logger.debug("human_click: 无法获取元素坐标，退化为普通 click()")
        await locator.click()
        return

    # 随机落点：控制在元素中心 30%~70% 区域内，避免边缘
    target_x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
    target_y = box["y"] + box["height"] * random.uniform(0.3, 0.7)

    # 分两段移动：先快速接近，再小幅修正（模拟人眼+手的协调）
    steps_approach = random.randint(*config.MOUSE_MOVE_STEPS_RANGE)
    mid_x = target_x + random.uniform(-8, 8)
    mid_y = target_y + random.uniform(-6, 6)
    await page.mouse.move(mid_x, mid_y, steps=steps_approach)
    await asyncio.sleep(random.uniform(*config.MOUSE_CORRECTION_PAUSE_RANGE))
    await page.mouse.move(target_x, target_y, steps=random.randint(*config.MOUSE_CORRECTION_STEPS_RANGE))

    # 随机停顿（人类在点击前有短暂定准时间）
    await asyncio.sleep(random.uniform(*config.CLICK_DELAY_RANGE))

    # 分开 mousedown / mouseup，按压时长由 config 控制
    await page.mouse.down()
    await asyncio.sleep(random.uniform(*config.CLICK_PRESS_DURATION_RANGE))
    await page.mouse.up()


async def hidden_click(page: Page, locator: Locator):
    """
    后台隐蔽点击：通过 JS 派发完整鼠标事件序列（mouseover/move/down/up/click），
    不移动系统光标，不干扰用户鼠标，适合后台多线程执行。
    事件携带真实坐标，对页面 JS 与真实点击无区别。
    """
    box = await locator.bounding_box()
    if not box:
        # 拿不到坐标时退化为 dispatch_event
        await locator.dispatch_event("click")
        return

    x = box["x"] + box["width"]  * random.uniform(0.25, 0.75)
    y = box["y"] + box["height"] * random.uniform(0.25, 0.75)

    await page.evaluate(
        """
        ([cx, cy]) => {
            const el = document.elementFromPoint(cx, cy);
            if (!el) return;
            const init = {
                bubbles: true, cancelable: true,
                view: window, button: 0, buttons: 1,
                clientX: cx, clientY: cy,
                screenX: cx + window.screenX,
                screenY: cy + window.screenY,
            };
            for (const type of ['mouseover','mouseenter','mousemove','mousedown','mouseup','click']) {
                el.dispatchEvent(new MouseEvent(type, init));
            }
        }
        """,
        [x, y],
    )
    # 短暂停顿，模拟按压节奏
    await asyncio.sleep(random.uniform(*config.CLICK_PRESS_DURATION_RANGE))


# ───────────────────────── 键盘行为 ─────────────────────────


async def human_type(page: Page, text: str):
    """
    逐字符输入，每个字符之间加入随机延迟，模拟人类打字节奏。
    偶尔会有一个更长的停顿（模拟"想一下"）。
    """
    for i, char in enumerate(text):
        await page.keyboard.type(char, delay=0)
        delay = random.uniform(*config.TYPING_DELAY_RANGE)
        # 大约每 5-10 个字符有一次较长的停顿（模拟「想一下」）
        if random.random() < 0.12:
            delay += random.uniform(*config.TYPING_THINK_PAUSE_RANGE)
        await asyncio.sleep(delay)


# ───────────────────────── 页面滚动 ─────────────────────────


async def random_scroll(page: Page, direction: str = "down"):
    """
    模拟人类向下/向上滚动页面。

    Parameters
    ----------
    page : Page
    direction : "down" | "up"
    """
    pixels = random.randint(*config.SCROLL_PIXELS_RANGE)
    delta = pixels if direction == "down" else -pixels
    await page.mouse.wheel(0, delta)
    await asyncio.sleep(random.uniform(*config.SCROLL_SETTLE_RANGE))
