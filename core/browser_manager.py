"""
browser_manager.py —— 浏览器生命周期高层管理
职责：Profile 同步、浏览器选择（优先复用运行中）、启动、IP 封禁后切换。
其他模块只需调用此处的两个接口，无需关心底层 API 和 CSV 细节。
"""

from __future__ import annotations

import asyncio

import config
from core.browser_factory import (
    fetch_all_profile_ids_from_api,
    get_running_browsers,
    launch_profile,
    stop_profile,
)
from exceptions import NoBrowserAvailableError
from utils.data_manager import (
    load_browsers,
    record_browser_ban,
    record_browser_launch,
    select_best_browser,
    select_best_running_browser,
    sync_browsers_from_api,
)
from utils.logger import get_logger

logger = get_logger(__name__)


async def sync_profiles_once() -> None:
    """
    Step 1：从 Nstbrowser API 同步 Profile 列表并写入 browsers.csv。

    main() 在启动所有 Worker 前调用一次，避免 N 个 Worker 各自重复调用 API。
    """
    try:
        api_profiles = await asyncio.to_thread(fetch_all_profile_ids_from_api)
    except Exception as exc:
        raise RuntimeError(f"拉取 Profile 列表失败: {exc}") from exc

    if not api_profiles:
        raise RuntimeError("未返回任何 Profile，请确认 Nstbrowser 客户端已启动")

    sync_browsers_from_api(api_profiles)
    browsers = load_browsers()
    logger.info("Step 1 | Profile 同步完成，共 %d 个 Profile 已写入 browsers.csv", len(browsers))


async def setup_and_acquire(
    exclude: set[str] | None = None,
    *,
    skip_sync: bool = False,
) -> tuple[str, str]:
    """
    Step 1 + Step 2：同步 Profile 列表（可跳过），选出并启动最佳浏览器。

    参数
    ----
    exclude   : 需要跳过的 profile_id 集合（已被本轮其他 Worker 占用），默认不排除。
    skip_sync : True 时跳过 Step 1 API 同步，供 main() 统一预同步后各 Worker 复用。

    返回
    ----
    (cdp_endpoint, profile_id)

    异常
    ----
    RuntimeError            : API 拉取失败或返回空列表
    NoBrowserAvailableError : 无可用 Profile
    Exception               : 浏览器启动失败
    """
    # ── Step 1: 同步 Profile（可跳过）────────────────────────────────
    if not skip_sync:
        await sync_profiles_once()
    else:
        logger.debug("Step 1 | 跳过 Profile 同步（已在启动前统一执行）")

    # ── Step 2: 优先复用已运行浏览器 ─────────────────────────────────
    logger.info("Step 2 | 检查是否有已运行的指纹浏览器...")
    try:
        running = await asyncio.wait_for(
            asyncio.to_thread(get_running_browsers),
            timeout=8.0,
        )
    except asyncio.TimeoutError:
        logger.warning("Step 2 | 查询运行中浏览器超时，视为无运行中浏览器")
        running = []

    if running:
        logger.info("Step 2 | 发现 %d 个运行中浏览器，检查封禁冷却期...", len(running))
        try:
            target = select_best_running_browser(running, exclude=exclude)
            logger.info(
                "Step 2 | 复用已运行浏览器: %s (%s)，端点: %s",
                target.get("name", ""), target["profile_id"], target["endpoint"],
            )
            return target["endpoint"], target["profile_id"]
        except NoBrowserAvailableError as exc:
            logger.warning("Step 2 | %s，将选择新浏览器...", exc)

    # ── Step 2: 无可复用 → 按策略选并启动（失败自动跳过，循环尝试）───
    logger.info("Step 2 | 无可复用的已运行浏览器，按策略选择 Profile...")
    failed_ids: set[str] = set()
    while True:
        best = select_best_browser(exclude=(exclude or set()) | failed_ids)
        target_id   = best["profile_id"]
        target_name = best.get("name", target_id)
        logger.info("Step 2 | 选中 Profile: %s (%s)，正在启动...", target_name, target_id)
        try:
            cdp_endpoint = await asyncio.to_thread(launch_profile, target_id)
        except Exception as exc:
            logger.warning(
                "Step 2 | Profile %s (%s) 启动失败（%s），跳过并尝试下一个...",
                target_name, target_id, exc,
            )
            record_browser_launch(target_id)  # 写入 last_launch_time，下次不再被优先选中
            failed_ids.add(target_id)
            continue
        break

    record_browser_launch(target_id)
    logger.info("Step 2 | 浏览器已启动，CDP 端点: %s", cdp_endpoint)
    return cdp_endpoint, target_id


async def switch_on_ban(
    current_profile_id: str,
    used_profile_ids: set[str],
) -> tuple[str, str]:
    """
    IP 封禁后：记录封禁时间、可选关闭当前浏览器、选并启动后备浏览器。

    返回
    ----
    (cdp_endpoint, new_profile_id)

    异常
    ----
    NoBrowserAvailableError : 没有可用后备浏览器
    Exception               : 后备浏览器启动失败
    """
    record_browser_ban(current_profile_id)

    if config.CLOSE_BROWSER_ON_IP_BAN:
        logger.info("Step X | 关闭当前浏览器 %s...", current_profile_id)
        await asyncio.to_thread(stop_profile, current_profile_id)

    # 循环尝试：若选中的 Profile 启动失败（如 API 400），将其加入排除集合后继续选下一个
    failed_ids: set[str] = set()
    while True:
        best = select_best_browser(exclude=used_profile_ids | failed_ids)
        new_id = best["profile_id"]
        try:
            cdp_endpoint = await asyncio.to_thread(launch_profile, new_id)
        except Exception as exc:
            logger.warning(
                "Step X | Profile %s (%s) 启动失败（%s），跳过并尝试下一个...",
                best.get("name", ""), new_id, exc,
            )
            record_browser_launch(new_id)  # 写入 last_launch_time，下次不再被优先选中
            failed_ids.add(new_id)
            continue  # 继续选下一个
        break

    record_browser_launch(new_id)
    logger.info("Step X | 已切换到新浏览器 %s，下一轮重试封IP账号...", new_id)
    return cdp_endpoint, new_id
