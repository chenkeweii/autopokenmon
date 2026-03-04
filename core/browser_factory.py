"""
browser_factory.py —— 浏览器工厂
职责：
  - launch_profile()  : 通过 Nstbrowser API v2 启动指定 Profile 浏览器
  - stop_profile()    : 关闭指定 Profile 浏览器
API v2 参考:
  StartBrowser  → POST   /api/v2/browsers/{profileId}
  StopBrowser   → DELETE /api/v2/browsers/{profileId}
  ConnectBrowser WS → ws://{host}/api/v2/connect/{profileId}?x-api-key=...&config=...
"""

from __future__ import annotations

import requests

import config
from exceptions import BrowserLaunchError
from utils.logger import get_logger

logger = get_logger(__name__)

# ───────────────────────── 公开接口 ─────────────────────────


def launch_profile(profile_id: str) -> str:
    """
    通过 HTTP API 启动 Nstbrowser Profile，返回 webSocketDebuggerUrl。

    Parameters
    ----------
    profile_id : str
        Nstbrowser 中已配置好的 Profile ID。

    Returns
    -------
    str
        浏览器暴露的 webSocketDebuggerUrl，可直接传给 Playwright connect_over_cdp。

    Raises
    ------
    BrowserLaunchError
        API 请求失败或返回异常。
    """
    url = f"http://{config.NST_HOST}/api/v2/browsers/{profile_id}"
    headers = {"x-api-key": config.NST_API_KEY}
    logger.info("正在通过 HTTP API 启动 Nst Profile: %s …", profile_id)

    try:
        resp = requests.post(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        raise BrowserLaunchError(
            f"Nstbrowser StartBrowser API 请求失败: {exc}"
        ) from exc

    if data.get("code") not in (0, 200):
        raise BrowserLaunchError(
            f"StartBrowser 返回错误: code={data.get('code')}, msg={data.get('msg')}"
        )

    ws_url = data.get("data", {}).get("webSocketDebuggerUrl")
    port = data.get("data", {}).get("port")

    if not ws_url and not port:
        raise BrowserLaunchError(
            f"无法从 API 响应中提取连接信息，完整响应: {data}"
        )

    # 优先用 webSocketDebuggerUrl，没有则用 port 构建
    endpoint = ws_url or f"http://127.0.0.1:{port}"
    logger.info("Profile %s 启动成功，CDP 端点: %s", profile_id, endpoint)
    return endpoint


def stop_profile(profile_id: str) -> bool:
    """
    通过 HTTP API 关闭指定 Profile 的浏览器实例。

    Returns
    -------
    bool
        关闭成功返回 True，失败返回 False（不抛异常，允许静默失败）。
    """
    url = f"http://{config.NST_HOST}/api/v2/browsers/{profile_id}"
    headers = {"x-api-key": config.NST_API_KEY}
    logger.info("正在关闭 Nst Profile: %s …", profile_id)

    try:
        resp = requests.delete(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") in (0, 200):
            logger.info("Profile %s 已成功关闭", profile_id)
            return True
        else:
            logger.warning("关闭 Profile %s 返回非零码: %s", profile_id, data)
            return False
    except requests.RequestException as exc:
        logger.warning("关闭 Profile %s 请求失败: %s", profile_id, exc)
        return False


def get_running_browsers() -> list[dict]:
    """
    调用 GET /api/v2/browsers 获取当前已启动的浏览器列表。

    Returns
    -------
    list[dict]
        每项包含 profile_id、name、port、endpoint 字段。
        若无正在运行的浏览器则返回空列表。
    """
    url = f"http://{config.NST_HOST}/api/v2/browsers"
    headers = {"x-api-key": config.NST_API_KEY}

    try:
        resp = requests.get(url, headers=headers, timeout=5)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.warning("查询运行中浏览器失败: %s", exc)
        return []

    if data.get("code") not in (0, 200):
        logger.warning("GET /api/v2/browsers 返回异常: %s", data)
        return []

    running = []
    for item in (data.get("data") or []):
        if not item.get("running"):
            continue
        port = item.get("remoteDebuggingPort")
        pid = item.get("profileId")
        if pid and port:
            running.append({
                "profile_id": pid,
                "name": item.get("name", ""),
                "port": port,
                "endpoint": f"http://127.0.0.1:{port}",
            })

    logger.info("当前运行中的浏览器: %d 个", len(running))
    return running


def fetch_all_profile_ids_from_api(page_size: int = 100) -> list[dict]:
    """
    从 Nstbrowser Profiles API 拉取所有 Profile（cursor 分页）。
    用于启动时同步 browsers.csv，无需手动维护 ID 列表。

    API: GET /api/v2/profiles/cursor?pageSize=100&direction=next&cursor=<cursor>

    Returns
    -------
    list[dict]
        每条包含 profile_id 和 name，顺序与 API 返回一致。

    Raises
    ------
    BrowserLaunchError
        API 请求失败时抛出。
    """
    headers = {"x-api-key": config.NST_API_KEY}
    url = f"http://{config.NST_HOST}/api/v2/profiles/cursor"
    all_profiles: list[dict] = []
    cursor: str | None = None
    page_num = 1

    while True:
        params: dict = {"pageSize": page_size}
        if cursor:
            params["direction"] = "next"
            params["cursor"] = cursor

        logger.info("拉取 Profile 列表，第 %d 批（pageSize=%d）…", page_num, page_size)

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            raise BrowserLaunchError(f"拉取 Profile 列表失败: {exc}") from exc

        if data.get("code") not in (0, 200):
            raise BrowserLaunchError(
                f"Profile 列表 API 返回错误: code={data.get('code')}, msg={data.get('msg')}"
            )

        payload = data.get("data", {})
        profiles = payload.get("docs", [])

        for p in profiles:
            pid = p.get("profileId") or p.get("id")
            if pid:
                all_profiles.append({
                    "profile_id": str(pid),
                    "name": p.get("name", ""),
                })

        has_more = payload.get("hasMore", False)
        cursor = payload.get("nextCursor")

        logger.info(
            "第 %d 批获取 %d 个 Profile，累计 %d，hasMore=%s",
            page_num, len(profiles), len(all_profiles), has_more,
        )

        if not has_more or not cursor or not profiles:
            break

        page_num += 1

    logger.info("共获取 %d 个 Profile", len(all_profiles))
    return all_profiles
