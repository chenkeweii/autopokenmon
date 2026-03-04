"""
cdp_handler.py —— CDP 连接生命周期管理
职责：通过 Playwright connect_over_cdp 接入已有浏览器实例，
      提供 page 对象给上层业务模块，并负责安全断开。
注意：本模块 **不** 创建新的 Browser 实例，仅连接已有实例。
"""

from __future__ import annotations

from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from exceptions import BrowserLaunchError
from utils.logger import get_logger

logger = get_logger(__name__)


class CDPSession:
    """
    管理一次 CDP 连接的完整生命周期。

    支持传入 webSocketDebuggerUrl 或 http://host:port 形式的端点。

    用法（async with 自动管理资源）::

        async with CDPSession(endpoint="ws://127.0.0.1:9222/...") as session:
            page = session.page
            await page.goto("https://example.com")
    """

    def __init__(self, endpoint: str):
        """
        Parameters
        ----------
        endpoint : str
            CDP 连接地址，来自 browser_factory.launch_profile() 的返回值。
            可以是 ws://... 或 http://... 格式。
        """
        self.endpoint = endpoint
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self.page: Page | None = None
        # 并发模式下，session_runner 通过 browser.new_context() 为每个账号创建独立 Session
        self.browser: Browser | None = None

    async def connect(self) -> Page:
        """
        建立 CDP 连接并返回可操作的 Page 对象。
        优先复用浏览器已有的页面，没有则新建。
        """
        logger.info("正在通过 CDP 连接浏览器: %s", self.endpoint)

        self._playwright = await async_playwright().start()

        try:
            self._browser = await self._playwright.chromium.connect_over_cdp(self.endpoint)
        except Exception as exc:
            await self._playwright.stop()
            raise BrowserLaunchError(
                f"CDP 连接失败（{self.endpoint}）: {exc}"
            ) from exc

        self.browser = self._browser  # 公开引用，供 session_runner 并发创建多个 Context

        # 优先复用现有 Context / Page
        contexts = self._browser.contexts
        if contexts:
            self._context = contexts[0]
            pages = self._context.pages
            self.page = pages[0] if pages else await self._context.new_page()
        else:
            self._context = await self._browser.new_context()
            self.page = await self._context.new_page()

        logger.info("CDP 连接成功，已获取 Page 对象")
        return self.page

    async def disconnect(self):
        """安全断开 CDP，释放 Playwright 资源（不关闭浏览器本体）。"""
        try:
            if self._browser:
                await self._browser.close()       # 只是断开连接
        except Exception:
            pass
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        logger.info("CDP 连接已断开 (%s)", self.endpoint)

    # ────────── async context manager ──────────
    async def __aenter__(self) -> "CDPSession":
        await self.connect()
        return self

    async def __aexit__(self, *_exc):
        await self.disconnect()
