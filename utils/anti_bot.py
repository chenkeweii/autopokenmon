"""
anti_bot.py —— 人类行为仿真工具集
职责：提供所有「让自动化看起来像人类」的原子操作。
      其他模块只需调用此处的函数，无需关心随机化细节。
"""

from __future__ import annotations

import asyncio
import math
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


async def random_scroll(page: Page, times: int = 2):
    """随机向下滚动若干次，模拟真人浏览页面内容。"""
    for _ in range(times):
        pixels = random.randint(*config.SCROLL_PIXELS_RANGE)
        await page.mouse.wheel(0, pixels)
        await asyncio.sleep(random.uniform(*config.SCROLL_SETTLE_RANGE))


async def page_idle_behavior(page: Page):
    """
    页面加载完成后的空闲行为（P0.2）：
    随机移动鼠标 + 偶尔小幅滚动，持续 2~4 秒，让 Gigya 采集到行为基线再操作。
    """
    total = random.uniform(2.0, 4.0)
    elapsed = 0.0
    actions = ["move", "move", "scroll", "pause"]  # 移动概率高于滚动
    while elapsed < total:
        act = random.choice(actions)
        if act == "move":
            viewport = page.viewport_size or {"width": 1280, "height": 720}
            x = random.randint(80, viewport["width"] - 80)
            y = random.randint(80, viewport["height"] - 80)
            steps = random.randint(*config.MOUSE_MOVE_STEPS_RANGE)
            await page.mouse.move(x, y, steps=steps)
            dt = random.uniform(0.2, 0.6)
        elif act == "scroll":
            pixels = random.randint(50, 200)
            await page.mouse.wheel(0, pixels)
            dt = random.uniform(*config.SCROLL_SETTLE_RANGE)
        else:
            dt = random.uniform(0.3, 0.8)
        await asyncio.sleep(dt)
        elapsed += dt


async def _bezier_mouse_move(page: Page, tx: float, ty: float):
    """
    沿三次贝塞尔曲线将鼠标从当前位置移动到 (tx, ty)。
    曲线由两个随机控制点决定，同时用 ease-in-out 速度曲线
    模拟「启动慢 → 中间快 → 接近目标减速」的自然节奏。
    所有中间坐标都通过 CDP Input.dispatchMouseEvent 发送，isTrusted=true。
    """
    pos = page.mouse
    sx = getattr(pos, "_x", None) or 0
    sy = getattr(pos, "_y", None) or 0

    dx, dy = tx - sx, ty - sy
    dist = math.hypot(dx, dy)
    # 步数与距离正相关，近距短步，远距多步，加少量随机
    steps = max(20, int(dist / 8) + random.randint(-5, 5))
    steps = min(steps, 80)

    # 随机控制点（偏移幅度与距离成比例）
    deviation = dist * random.uniform(0.15, 0.35)
    cp1x = sx + dx * random.uniform(0.1, 0.4) + random.uniform(-deviation, deviation)
    cp1y = sy + dy * random.uniform(0.1, 0.4) + random.uniform(-deviation, deviation)
    cp2x = sx + dx * random.uniform(0.6, 0.9) + random.uniform(-deviation * 0.5, deviation * 0.5)
    cp2y = sy + dy * random.uniform(0.6, 0.9) + random.uniform(-deviation * 0.5, deviation * 0.5)

    for i in range(1, steps + 1):
        t = i / steps
        mt = 1 - t
        x = mt**3 * sx + 3 * mt**2 * t * cp1x + 3 * mt * t**2 * cp2x + t**3 * tx
        y = mt**3 * sy + 3 * mt**2 * t * cp1y + 3 * mt * t**2 * cp2y + t**3 * ty
        # 中段加轻微高斯抖动，模拟手部肌肉颤动
        if 0.1 < t < 0.9:
            x += random.gauss(0, 0.4)
            y += random.gauss(0, 0.4)
        await page.mouse.move(x, y)
        # ease-in-out：中间快，两端慢
        speed = 0.5 - 0.5 * math.cos(math.pi * t)
        delay = (0.004 + 0.012 * (1 - speed)) * random.uniform(0.8, 1.2)
        await asyncio.sleep(delay)


async def human_click(page: Page, locator: Locator):
    """
    模拟人类点击（贝塞尔轨迹版）：
    1. 获取元素坐标，随机落点偏离中心
    2. 沿贝塞尔曲线移动鼠标（ease-in-out + 微抖），isTrusted=true
    3. 靠近目标后小幅修正（模拟人眼+手协调的二段移动）
    4. 随机按压时长，模拟真实手指节奏
    """
    box = await locator.bounding_box()
    if not box:
        logger.debug("human_click: 无法获取元素坐标，退化为普通 click()")
        await locator.click()
        return

    # 随机落点：控制在元素中心 25%~75% 区域，避免边缘极值和完美中心
    target_x = box["x"] + box["width"]  * random.uniform(0.25, 0.75)
    target_y = box["y"] + box["height"] * random.uniform(0.25, 0.75)

    # 第一段：贝塞尔曲线移动到目标附近（有 ±6px 过冲）
    overshoot_x = target_x + random.uniform(-6, 6)
    overshoot_y = target_y + random.uniform(-5, 5)
    await _bezier_mouse_move(page, overshoot_x, overshoot_y)

    # 第二段：小幅精准修正（模拟人眼重新定准）
    await asyncio.sleep(random.uniform(*config.MOUSE_CORRECTION_PAUSE_RANGE))
    await page.mouse.move(
        target_x, target_y,
        steps=random.randint(*config.MOUSE_CORRECTION_STEPS_RANGE),
    )

    # 点击前停顿（定准时间）
    await asyncio.sleep(random.uniform(*config.CLICK_DELAY_RANGE))

    # mousedown → 短暂按压 → mouseup
    await page.mouse.down()
    await asyncio.sleep(random.uniform(*config.CLICK_PRESS_DURATION_RANGE))
    await page.mouse.up()


# hidden_click 已移除：
# 它通过 JS new MouseEvent() 派发事件，isTrusted=false，会被 Gigya 等风控系统识别。
# 所有点击请使用 human_click()，CDP 派发的事件 isTrusted=true 且轨迹真实。


# ───────────────────────── 键盘行为 ─────────────────────────


async def human_type(page: Page, text: str):
    """
    逐字符输入，模拟真人打字节奏：
    - 字符间隔服从正态分布（而非均匀分布），更像真实键盘节奏
    - 约 10% 概率出现「思考停顿」
    - 约 4% 概率发生误输入（多打一个字符后退格修正），仅对字母/数字触发
    键盘事件通过 CDP 发送，isTrusted=true。
    """
    lo, hi = config.TYPING_DELAY_RANGE
    mu    = (lo + hi) / 2
    sigma = (hi - lo) / 4  # ~95% 落在 [lo, hi] 内

    for char in text:
        # 偶发误输入（仅对字母/数字，4% 概率）
        if char.isalnum() and random.random() < 0.04:
            typo = random.choice("abcdefghjklmnpqrstuvwxyz")
            await page.keyboard.type(typo, delay=0)
            await asyncio.sleep(max(0.03, random.gauss(mu * 0.6, sigma)))
            await page.keyboard.press("Backspace")
            await asyncio.sleep(max(0.05, random.gauss(mu * 0.8, sigma)))

        await page.keyboard.type(char, delay=0)

        delay = max(lo * 0.5, random.gauss(mu, sigma))
        if random.random() < 0.10:
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
