from __future__ import annotations
import asyncio
import os
import sys

# 确保脚本所在目录在 sys.path 最前（嵌入式 Python 不自动添加）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(
    sys.executable if getattr(sys, "frozen", False) else __file__
))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
os.chdir(_SCRIPT_DIR)

# Python 3.8+ 修改了 DLL 搜索路径：加载 .pyd 扩展时不再搜索 PATH，
# 需要用 os.add_dll_directory() 显式注册嵌入式 Python 目录，
# 否则 vcruntime140.dll 等依赖在目标机器上找不到。
if hasattr(os, 'add_dll_directory'):
    _python_dir = os.path.join(_SCRIPT_DIR, 'python')
    if os.path.isdir(_python_dir):
        os.add_dll_directory(_python_dir)

# 屏蔽 Playwright 内部 Node.js 进程的废弃 API 警告（如 DEP0169 url.parse）
os.environ.setdefault("NODE_NO_WARNINGS", "1")

import config
from core.browser_manager import setup_and_acquire, switch_on_ban, sync_profiles_once
from core.cdp_handler import CDPSession
from modules.session_runner import run_accounts
from utils.data_manager import load_pending_accounts
from utils.email_fetcher import start_idle_monitor, stop_idle_monitor
from utils.logger import get_logger, set_worker_id
from utils.notifier import send_notify

logger = get_logger(__name__)


def _split_accounts(accounts: list[dict], n: int) -> list[list[dict]]:
    """
    将账号列表轮询分配成 n 份。
    例：10 个账号、n=3 → [0,3,6], [1,4,7], [2,5,8,9]
    空分片（账号数 < n）会被过滤掉。
    """
    slices: list[list[dict]] = [[] for _ in range(n)]
    for i, acc in enumerate(accounts):
        slices[i % n].append(acc)
    return [s for s in slices if s]


async def _run_worker(
    worker_id: int,
    initial_accounts: list[dict],
    email_tasks: list,
    profile_lock: asyncio.Lock,
    used_profile_ids: set[str],
) -> str:
    """
    单个 Worker 协程：
      1. 获取一个专属指纹浏览器（加锁避免两个 Worker 抢到同一个 Profile）
      2. 顺序处理分配给自己的账号
      3. 遇到 IP 封禁则切换浏览器，重新加载本 Worker 负责的 status=3 账号重试
      4. 无可用浏览器或账号处理完毕后退出

    返回：描述本 Worker 退出原因的字符串（供汇总日志用）。
    """
    # 绑定 Worker 标签：此 Task 内的所有日志自动带 [W{id}] 前缀
    set_worker_id(worker_id)

    # 记录本 Worker 负责的账号 username 集合（用于 IP 封禁后筛出 status=3 重试）
    my_usernames = {a["username"] for a in initial_accounts}

    # ── Step 1-2: 获取专属浏览器（加锁，避免多 Worker 同时拿到相同 Profile）──
    logger.info("正在获取指纹浏览器...")
    try:
        async with profile_lock:
            cdp_endpoint, profile_id = await setup_and_acquire(
                exclude=used_profile_ids, skip_sync=True
            )
            used_profile_ids.add(profile_id)
    except Exception as exc:
        logger.error("浏览器初始化失败: %s", exc)
        raise RuntimeError(f"浏览器初始化失败: {exc}") from exc

    current_accounts = initial_accounts

    while True:
        if not current_accounts:
            break

        logger.info("Profile=%s，处理 %d 个账号", profile_id, len(current_accounts))

        # ── Steps 4-11: CDP Session 内顺序处理账号 ──────────────────────────
        async with CDPSession(endpoint=cdp_endpoint) as session:
            ip_banned = await run_accounts(session.browser, current_accounts, email_tasks)

        if not ip_banned:
            break  # 正常完成，退出 Worker 循环

        # ── Step X: IP 封禁，切换浏览器后重载本 Worker 的 status=3 账号 ──────
        logger.warning("IP 封禁确认，切换指纹浏览器...")
        try:
            async with profile_lock:
                cdp_endpoint, profile_id = await switch_on_ban(
                    profile_id, used_profile_ids
                )
                used_profile_ids.add(profile_id)
        except Exception as exc:
            logger.error("无可用后备浏览器，放弃重试: %s", exc)
            raise RuntimeError(f"无可用后备浏览器: {exc}") from exc

        # 重新加载属于本 Worker 的 status=3 账号
        all_retry = load_pending_accounts()  # 返回 status=0 和 status=3
        current_accounts = [a for a in all_retry if a["username"] in my_usernames]
        if not current_accounts:
            logger.info("切换浏览器后无需重试的账号，Worker 退出")
            break
        logger.info("切换浏览器后重试 %d 个账号", len(current_accounts))

    return f"Worker {worker_id} 完成"


async def main():
    logger.info("========== Pokemon 自动预约系统启动 ==========")
    exit_subject = "程序退出"
    exit_body    = ""

    # Step 0: REQUIRE_OTP 或 REQUIRE_APPOINT_EMAIL 任一为 True 时才启动 IMAP IDLE 监听
    if config.REQUIRE_OTP or config.REQUIRE_APPOINT_EMAIL:
        monitor_task = start_idle_monitor(config.OTP_EMAIL_ADDR, config.OTP_EMAIL_AUTH_CODE)
        await asyncio.sleep(0)  # 让监听任务立即被调度
        logger.info("Step 0 | 后台 IDLE 邮件监听已启动")
    else:
        monitor_task = None
        logger.info("Step 0 | [调试] REQUIRE_OTP=False 且 REQUIRE_APPOINT_EMAIL=False，跳过 IDLE 邮件监听")

    email_tasks: list[asyncio.Task] = []   # 跨所有 Worker 共享的邮件确认后台任务列表

    try:
        # Step 3: 读取全部待处理账号，按 Worker 数轮询分配
        logger.info("Step 3 | 读取待预约账号...")
        pending = load_pending_accounts()
        if not pending:
            logger.info("Step 3 | 没有待处理账号，退出")
            exit_subject = "运行完成"
            exit_body    = "没有待处理账号，程序退出。"
            return

        n_workers = min(config.CONCURRENT_BROWSERS, len(pending))
        logger.info(
            "Step 3 | 共 %d 个待处理账号，启动 %d 个并发 Worker",
            len(pending), n_workers,
        )
        slices = _split_accounts(pending, n_workers)

        # ── Android 模式：跳过 Nstbrowser，直连手机 Chrome ──────────────────
        if config.ANDROID_MODE:
            logger.info("Step 1 | [Android] 直连模式，跳过 Profile 同步")
            cdp_endpoint = f"http://127.0.0.1:{config.ANDROID_CDP_PORT}"
            logger.info("Step 1 | [Android] CDP 端点: %s", cdp_endpoint)
            async with CDPSession(endpoint=cdp_endpoint) as session:
                await run_accounts(session.browser, pending, email_tasks)
            exit_subject = "运行完成"
            exit_body    = f"Android 模式，共处理 {len(pending)} 个账号"
            return

        # ── 正常模式：Nstbrowser ──────────────────────────────────────────────
        # Step 1: 统一同步一次 Profile（所有 Worker 共用，避免重复调用 Nstbrowser API）
        logger.info("Step 1 | 启动前同步 Profile 列表...")
        await sync_profiles_once()

        # 跨 Worker 共享：Profile 选择锁 + 已用 Profile 集合
        profile_lock     = asyncio.Lock()
        used_profile_ids: set[str] = set()

        # 启动所有 Worker 协程并发运行
        worker_tasks = [
            asyncio.create_task(
                _run_worker(
                    worker_id        = i + 1,
                    initial_accounts = slices[i],
                    email_tasks      = email_tasks,
                    profile_lock     = profile_lock,
                    used_profile_ids = used_profile_ids,
                )
            )
            for i in range(len(slices))
        ]

        results = await asyncio.gather(*worker_tasks, return_exceptions=True)
        failed_workers: list[int] = []
        for i, r in enumerate(results, start=1):
            if isinstance(r, Exception):
                logger.error("Worker %d | 未捕获异常: %s", i, r)
                failed_workers.append(i)
            else:
                logger.info("Worker %d | %s", i, r)

        if failed_workers:
            exit_subject = f"部分完成 · {len(failed_workers)}/{n_workers} 个 Worker 异常"
            exit_body = (
                f"{n_workers} 个 Worker 中，{len(failed_workers)} 个异常退出"
                f"（Worker {failed_workers}）。\n"
                f"其余 {n_workers - len(failed_workers)} 个 Worker 正常完成。\n"
                "异常 Worker 处理的账号可能未全部完成，请查看日志后手动确认。"
            )
        else:
            exit_subject = "运行完成"
            exit_body    = f"所有 {n_workers} 个 Worker 正常完成，账号处理完毕。"

    except asyncio.CancelledError:
        logger.info("收到取消信号，正在退出...")
        exit_subject = "手动停止"
        exit_body    = "程序收到取消信号（CancelledError）已停止。"
        raise
    except Exception as exc:
        exc_type = type(exc).__name__
        if isinstance(exc, (TimeoutError,)) or "TimeoutError" in exc_type:
            first_line = str(exc).split("\n")[0].strip()
            logger.error("运行失败 [超时]: %s", first_line)
            exit_subject = "运行失败 · 超时"
            exit_body    = f"运行时发生超时异常：\n{first_line}"
        else:
            logger.error("运行失败: %s", exc)
            exit_subject = "运行失败 · 异常"
            exit_body    = f"未捕获异常 ({exc_type})：\n{exc}"
    finally:
        logger.info("========== 程序结束，浏览器保持打开 ==========")
        # 发送退出通知
        if exit_body:
            await asyncio.to_thread(send_notify, exit_subject, exit_body)
        # 统一等待所有邮件确认后台任务（手动停止时最多等 3 秒，超时直接取消）
        try:
            _pending_email = [t for t in email_tasks if not t.done()]
            if _pending_email:
                logger.info("finally | 等候 %d 个残留邮件确认后台任务...", len(_pending_email))
                for t in _pending_email:
                    t.cancel()
                await asyncio.wait(_pending_email, timeout=3)
        except Exception:
            pass
        # 停止 IDLE 监听（最多等 6 秒，超时直接放弃）
        if monitor_task is not None:
            stop_idle_monitor()
            try:
                await asyncio.wait_for(asyncio.shield(monitor_task), timeout=6)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass



