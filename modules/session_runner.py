"""
session_runner.py —— 单次 CDP Session 内的账号处理循环
职责：在单个 Browser 内顺序处理分配给本 Worker 的账号，
      依次执行登录 → 预约 → 标记结果，内置 IP 封禁判定状态机。

并发模式
--------
并发在 **浏览器 Worker** 层实现（main.py 同时启动 config.CONCURRENT_BROWSERS
个独立 Worker，每个 Worker 持有一个指纹浏览器 + 独立代理 IP，
处理属于自己的那批账号）。
本模块内部始终顺序处理，避免同一 IP 下同时请求带来的风险。

接口
----
run_accounts(browser, accounts, email_tasks) -> bool
    返回 True  表示检测到 IP 封禁，调用方（Worker）应切换浏览器后重试。
    返回 False 表示正常完成（含部分账号失败但非 IP 封禁）。
"""

from __future__ import annotations

import asyncio

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

import config
from exceptions import AppointmentError, LoginError, AccountNeedsResetError
from modules.appoint_logic import make_appointment
from modules.login_logic import login
from utils.data_manager import mark_account_status
from utils.email_fetcher import wait_for_appointment_confirm
from utils.logger import get_logger
from utils.notifier import send_notify

logger = get_logger(__name__)


class _AppointTimeoutExhausted(Exception):
    """内部异常：预约超时且重试次数已耗尽，触发 status=5 流程。"""


# ──────────────────────────────────────────────────────────────────────
# 邮件确认后台任务
# ──────────────────────────────────────────────────────────────────────

async def _verify_email_background(username: str, submit_ts: float) -> None:
    """
    后台任务：等待预约确认邮件。
    - 收到邮件 → 标 status=1（正式确认）
    - 超时未收 → 保留 status=4，记录 WARNING（可手动核查）
    """
    mail = await wait_for_appointment_confirm(
        since_ts=submit_ts,
        recipient=username,
        timeout_seconds=config.APPOINT_CONFIRM_WAIT,
    )
    if mail is not None:
        mark_account_status(username, 1)
        logger.info("账号 %s | ✓ 邮件确认到达，已更新 status=1 | received=%s",
                    username, mail.get("original_received_at", "-"))
    else:
        logger.warning(
            "账号 %s | 预约确认邮件在 %ds 内未到（可能延迟），保留 status=4 待手动核查",
            username, config.APPOINT_CONFIRM_WAIT,
        )


async def _process_one_account(
    page,
    idx: int,
    total: int,
    account: dict,
    shared: dict,
    email_tasks: list,
) -> None:
    """
    在 page 上执行完整的「登录 → 预约 → 标记」流程。
    通过 shared + lock 与其他并发账号共享 IP 封禁判定状态。
    """
    username = account["username"]
    logger.info("-" * 60)
    logger.info("账号 %d/%d | %s", idx, total, username)

    try:
        # ── 封 IP 模拟短路（仅调试用）─────────────────────────────────────
        # 注意：idx 是当前 Worker 内的局部编号（1 起步），多 Worker 时每个 Worker 均独立计数
        if config.SIMULATE_IP_BAN_FROM_ACCOUNT > 0 and idx >= config.SIMULATE_IP_BAN_FROM_ACCOUNT:
            logger.warning(
                "账号 %s | [调试] SIMULATE_IP_BAN_FROM_ACCOUNT=%d，强制触发登录失败",
                username, config.SIMULATE_IP_BAN_FROM_ACCOUNT,
            )
            raise LoginError("メールアドレスまたはパスワードが一致しませんでした。")
        # ──────────────────────────────────────────────────────────────────

        await login(page, username, account["password"])

        # 登录成功：解决待裁决账号（它们是账号自身问题，非封 IP）
        # success_count 在登录成功后即自增（不等待预约结果）：
        # 封 IP 检测的关键是「能否登录」而非「能否预约」。
        # 注：单 Worker 内账号顺序处理，无并发，无需 Lock。
        shared["success_count"] += 1
        shared["consecutive_failures"] = 0   # 登录成功，重置连续失败计数
        if shared["pending_verdicts"]:
            for pv in shared["pending_verdicts"]:
                mark_account_status(pv["username"], 2, pv["error_text"])
                logger.info(
                    "账号 %s | 登录成功，前序待裁决账号 %s 确认为普通登录失败，已标记 status=2",
                    username, pv["username"],
                )
            shared["pending_verdicts"].clear()

        # ── 预约（带超时重试）──────────────────────────────────────────────
        submit_ts = None
        for _attempt in range(1, config.APPOINT_RETRY_TIMES + 2):
            try:
                submit_ts = await make_appointment(page, username)
                break  # 成功，退出重试循环
            except AppointmentError:
                raise  # 商品找不到等业务错误，不重试
            except Exception as _exc:
                _is_timeout = isinstance(
                    _exc, (PlaywrightTimeoutError, asyncio.TimeoutError, TimeoutError)
                )
                if _is_timeout and _attempt <= config.APPOINT_RETRY_TIMES:
                    logger.warning(
                        "账号 %s | 预约超时（第 %d/%d 次），等待 %ds 后重新加载预约页重试: %s",
                        username, _attempt, config.APPOINT_RETRY_TIMES + 1,
                        config.APPOINT_RETRY_WAIT,
                        str(_exc).split("\n")[0].strip(),
                    )
                    await asyncio.sleep(config.APPOINT_RETRY_WAIT)
                    _retry_url = (
                        config.APPOINTMENT_LOCAL_URL
                        if not config.DO_CLICK_LOGIN
                        else config.POKEMON_APPOINTMENT_URL
                    )
                    _retry_wait_until = "load" if not config.DO_CLICK_LOGIN else "domcontentloaded"
                    await page.goto(
                        _retry_url,
                        wait_until=_retry_wait_until,
                        timeout=config.PAGE_LOAD_TIMEOUT_MS,
                    )
                elif _is_timeout:
                    raise _AppointTimeoutExhausted(str(_exc)) from _exc
                else:
                    raise  # 非超时错误 → 交给外层 except

        # ── 标记预约结果 ────────────────────────────────────────────────────
        if config.REQUIRE_APPOINT_EMAIL:
            mark_account_status(username, 4)
            logger.info("账号 %s | 预约已提交，标记 status=4，后台等待邮件确认", username)
            task = asyncio.create_task(_verify_email_background(username, submit_ts))
            email_tasks.append(task)
            logger.debug("账号 %s | 邮件确认后台任务已创建", username)
        else:
            mark_account_status(username, 1)
            logger.info("账号 %s | ✓ 预约成功，已标记 status=1", username)

    except AccountNeedsResetError as exc:
        # 账号需重置密码，与 IP 封禁无关：直接标 status=2，不累计 consecutive_failures
        logger.warning("账号 %s | 需重置密码，直接标记 status=2: %s", username, exc)
        mark_account_status(username, 2, str(exc))

    except LoginError as exc:
        error_text = str(exc)
        if shared["ip_ban"]:
            # IP 封禁已在上个账号确认，本账号同样标 status=3
            mark_account_status(username, 3, error_text)
            logger.warning("账号 %s | IP 封禁已确认（上个账号触发），标记 status=3", username)
        else:
            # 无论之前是否有成功记录，连续失败达阈值即判定 IP 封禁
            shared["consecutive_failures"] += 1
            shared["pending_verdicts"].append({"username": username, "error_text": error_text})
            logger.warning(
                "账号 %s | 登录失败（连续第 %d 次 / 阈值 %d），暂存待封禁裁决: %s",
                username, shared["consecutive_failures"],
                config.IP_BAN_CONFIRM_THRESHOLD, error_text,
            )
            if shared["consecutive_failures"] >= config.IP_BAN_CONFIRM_THRESHOLD:
                logger.error(
                    "连续 %d 个账号登录失败，达到封 IP 阈值，判定 IP 封禁，均标记 status=3",
                    shared["consecutive_failures"],
                )
                for pv in shared["pending_verdicts"]:
                    mark_account_status(pv["username"], 3, pv["error_text"])
                shared["pending_verdicts"].clear()
                shared["ip_ban"] = True

    except AppointmentError as exc:
        logger.warning("账号 %s | 预约失败，跳过: %s", username, exc)

    except _AppointTimeoutExhausted as exc:
        err_msg  = str(exc).split("\n")[0].strip()
        full_msg = (
            f"预约超时，已等待重试 {config.APPOINT_RETRY_TIMES} 次仍失败。\n"
            f"账号：{username}\n错误：{err_msg}"
        )
        mark_account_status(username, 5, f"超时重试耗尽: {err_msg}")
        logger.error("账号 %s | 预约超时重试耗尽，标记 status=5", username)
        await asyncio.to_thread(send_notify, f"账号预约超时 · {username}", full_msg)

    except Exception as exc:
        if isinstance(exc, (PlaywrightTimeoutError, asyncio.TimeoutError, TimeoutError)):
            logger.error("账号 %s | 超时: %s", username, str(exc).split("\n")[0].strip())
        else:
            logger.error("账号 %s | 意外异常（%s）: %s", username, type(exc).__name__, exc)


# ──────────────────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────────────────

async def run_accounts(
    browser,
    accounts: list[dict],
    email_tasks: list | None = None,
) -> bool:
    """
    在 browser 上顺序处理 accounts，返回是否检测到 IP 封禁。

    browser    : Playwright Browser 对象（来自 CDPSession.browser）。
                 每个账号独立创建 BrowserContext，确保 Cookie / Session 完全隔离，
                 Context 关闭即等效于退出登录，无需显式调用 logout()。
    email_tasks: 由调用方（main.py）提供的共享列表，用于收集后台邮件确认任务。
                 传入外部列表时本函数不内部 gather，由 main.py finally 统一 await。

    并发说明
    --------
    并发是在 **浏览器 Worker** 层实现的（main.py 同时启动多个 Worker，
    每个 Worker 持有一个独立指纹浏览器 + 独立代理 IP）。
    本函数内部保持顺序处理，同一时刻只有一个账号在运行，
    避免同一 IP 下同时发起多个登录请求而增加风险。
    """
    _own_tasks = email_tasks is None
    if _own_tasks:
        email_tasks = []

    # 复用 Nstbrowser 默认 Context（始终保持 1 个标签页）。
    # 账号在同一 Worker 内顺序处理，无并发冲突；
    # 每个账号开始前清空 Cookie 以确保账号隔离，等效于独立 Context 的效果。
    if browser.contexts:
        _default_ctx = browser.contexts[0]
        _shared_page = (
            _default_ctx.pages[0] if _default_ctx.pages
            else await _default_ctx.new_page()
        )
    else:
        _default_ctx = await browser.new_context()
        _shared_page = await _default_ctx.new_page()

    # IP 封禁状态（单 Worker 内顺序执行，无需 Lock）
    shared = {
        "success_count":      0,
        "consecutive_failures": 0,   # 连续登录失败计数，成功时清零
        "pending_verdicts":  [],     # list[{"username": str, "error_text": str}]
        "ip_ban":            False,
    }

    for idx, account in enumerate(accounts, start=1):
        if shared["ip_ban"]:
            break  # 已确认封 IP，后续账号无需继续

        try:
            # 清空上一账号遗留的 Cookie / 本地存储，保证账号间隔离
            await _default_ctx.clear_cookies()
            await _shared_page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
            await _shared_page.goto("about:blank", wait_until="commit")
            await _process_one_account(_shared_page, idx, len(accounts), account, shared, email_tasks)
        except Exception as exc:
            logger.error("账号 %s | Context 层意外异常: %s", account["username"], exc)

    # 循环结束，处理残留的待裁决账号（最后账号失败但后无账号可裁决）
    if shared["pending_verdicts"] and not shared["ip_ban"]:
        for pv in shared["pending_verdicts"]:
            mark_account_status(pv["username"], 2, pv["error_text"])
            logger.info(
                "循环结束，待裁决账号 %s 连续失败未达封禁阈值，按普通登录失败标记 status=2",
                pv["username"],
            )

    # 等候尚未完成的邮件确认后台任务（仅当任务列表由本函数自己管理时）
    if _own_tasks and email_tasks:
        remaining = [t for t in email_tasks if not t.done()]
        if remaining:
            logger.info("等候 %d 个账号的邮件确认结果...", len(remaining))
            await asyncio.gather(*remaining, return_exceptions=True)

    logger.info("所有账号处理完毕")
    return shared["ip_ban"]

