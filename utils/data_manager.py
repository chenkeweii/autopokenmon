"""
data_manager.py —— 数据层统一入口
职责：所有 CSV 的读写都在此模块完成，其他模块禁止直接操作文件。

管理两份数据文件：
  accounts.csv  — 账号信息（用户名、密码、是否已预约）
  browsers.csv  — 浏览器环境信息（Profile ID、上次启动时间、上次封禁时间）

注意：此模块使用 stdlib csv，不依赖 pandas。
      后续迁移数据库时只需修改此文件的读写实现。
"""

from __future__ import annotations

import csv
import os
import threading
from datetime import datetime, timedelta

import config
from exceptions import NoBrowserAvailableError
from utils.logger import get_logger

logger = get_logger(__name__)

_FMT = "%Y-%m-%d %H:%M:%S"  # 统一时间格式，供所有读写时间字段的函数使用

# 写锁：防止多 Worker 并发写 CSV 时互相覆盖
# 使用 threading.Lock 而非 asyncio.Lock，兼容 run_in_executor 场景
_csv_write_lock = threading.Lock()

# status: 0=未尝试 / 1=预约已确认（邮件到达）/ 2=登录失败 / 3=IP封禁待重试 / 4=已提交待邮件确认 / 5=超时重试耗尽（特殊故障，需人工核查）
_ACCOUNTS_COLS = ["username", "password", "status", "error_message"]
_BROWSERS_COLS = ["name", "profile_id", "last_launch_time", "last_ban_time"]


# ══════════════════════════════════════════════
#   accounts.csv 操作
# ══════════════════════════════════════════════

def load_pending_accounts() -> list[dict]:
    """读取 accounts.csv，返回所有 status=0（未尝试）或 status=3（IP封禁待重试）的账号列表。
    排序：status=3 优先于 status=0（封IP待重试的账号先跟。）
    """
    rows = _read_csv(config.ACCOUNTS_CSV_PATH, _ACCOUNTS_COLS)
    pending = [r for r in rows if r["status"].strip() in ("0", "3")]
    pending.sort(key=lambda r: 0 if r["status"].strip() == "3" else 1)  # status=3 优先（封IP待重试先跑）
    logger.info("账号文件共 %d 条，待预约 %d 条", len(rows), len(pending))
    return pending


def mark_account_status(username: str, status: int, error_message: str = "") -> None:
    """
    更新账号状态并回写文件。
      status: 0=未尝试, 1=预约成功, 2=登录失败（账号自身原因）, 3=IP封禁可重试（换浏览器/IP后重跑）
      error_message: 登录失败时页面显示的错误原文（其他状态传空字符串即可）
    """
    rows = _read_csv(config.ACCOUNTS_CSV_PATH, _ACCOUNTS_COLS)
    found = False
    for row in rows:
        if row["username"] == username:
            row["status"] = str(status)
            row["error_message"] = error_message
            found = True
    if not found:
        logger.warning("mark_account_status: 未找到账号 %s", username)
        return
    _write_csv(config.ACCOUNTS_CSV_PATH, _ACCOUNTS_COLS, rows)
    logger.debug("账号 %s 状态已更新 → %d（错误：%s）", username, status, error_message or "无")


# ══════════════════════════════════════════════
#   browsers.csv 操作
# ══════════════════════════════════════════════

def load_browsers() -> list[dict]:
    """读取 browsers.csv，返回全部浏览器环境列表。"""
    return _read_csv(config.BROWSERS_CSV_PATH, _BROWSERS_COLS, required=False)


def sync_browsers_from_api(api_profiles: list[dict]) -> None:
    """
    将 Nstbrowser API 返回的 Profile 列表覆写到 browsers.csv：
    - 以 API 列表为唯一来源，覆盖本地全部记录
    - 若本地已有该 Profile → 保留其历史时间字段（last_launch_time / last_ban_time）
    - 本地有但 API 不返回 → 从 CSV 中删除
    """
    rows = _read_csv(config.BROWSERS_CSV_PATH, _BROWSERS_COLS, required=False)
    existing = {r["profile_id"]: r for r in rows}

    new_rows: list[dict] = []
    for p in api_profiles:
        pid  = p["profile_id"]
        name = p.get("name", "")
        if pid in existing:
            # 保留历史时间数据，仅更新 name
            existing[pid]["name"] = name
            new_rows.append(existing[pid])
        else:
            new_rows.append({
                "name": name, "profile_id": pid,
                "last_launch_time": "", "last_ban_time": "",
            })

    removed = len(existing) - sum(1 for r in new_rows if r["profile_id"] in existing)
    logger.info(
        "browsers.csv 覆写完成：API %d 个，本地原有 %d 个，移除 %d 个",
        len(api_profiles), len(existing), removed,
    )

    _write_csv(config.BROWSERS_CSV_PATH, _BROWSERS_COLS, new_rows)


def select_best_running_browser(running_list: list[dict], exclude: set | None = None) -> dict:
    """
    从当前已运行的浏览器中，找出第一个未在 IP 封禁冷却期内的浏览器。

    参数
    ----
    running_list : list[dict]
        get_running_browsers() 返回的列表，每项包含 profile_id / name / endpoint 等字段。
    exclude : set | None
        需要跳过的 profile_id 集合（已被本轮其他 Worker 占用），默认不排除任何。

    返回
    ----
    dict : running_list 中第一个封禁冷却已过期的项，直接包含 endpoint 字段。

    异常
    ----
    NoBrowserAvailableError : 所有已运行浏览器均在冷却期内或已被本轮 Worker 占用。
    """
    # 先排除已被其他 Worker 占用的浏览器
    exclude = exclude or set()
    running_list = [item for item in running_list if item["profile_id"] not in exclude]
    if not running_list:
        raise NoBrowserAvailableError("所有已运行浏览器均已被本轮其他 Worker 占用，将选择新浏览器")

    csv_rows = _read_csv(config.BROWSERS_CSV_PATH, _BROWSERS_COLS, required=False)
    ban_map  = {r["profile_id"]: r["last_ban_time"] for r in csv_rows}  # pid → ban时间

    min_interval = timedelta(seconds=config.MIN_RETRY_INTERVAL)

    for item in running_list:
        pid      = item["profile_id"]
        ban_time = ban_map.get(pid, "")  # 不在 CSV 里就当未封禁过

        if not ban_time:
            logger.info(
                "Step 2 | 已运行浏览器 %s (%s) 未记录封禁历史，可复用",
                item.get("name", ""), pid,
            )
            return item

        try:
            ban_dt  = datetime.strptime(ban_time, _FMT)
            elapsed = datetime.now() - ban_dt
        except Exception:
            # 时间格式异常就当未封禁过
            return item

        if elapsed >= min_interval:
            logger.info(
                "Step 2 | 已运行浏览器 %s (%s) 封禁冷却已到期（%s），可复用",
                item.get("name", ""), pid, elapsed,
            )
            return item

        remaining = min_interval - elapsed
        total_sec = int(remaining.total_seconds())
        h, rem    = divmod(total_sec, 3600)
        m, s      = divmod(rem, 60)
        logger.warning(
            "Step 2 | 已运行浏览器 %s (%s) 仍在 IP 封禁冷却期，距离冷却到期还差: %dh %dm %ds",
            item.get("name", ""), pid, h, m, s,
        )

    raise NoBrowserAvailableError("所有已运行浏览器均在 IP 封禁冷却期内")


def select_best_browser(exclude: set | None = None) -> dict:
    """
    从 browsers.csv 中按策略选出最适合启动的浏览器。

    参数
    ----
    exclude : set | None
        需要跳过的 profile_id 集合（例如本轮已使用过的浏览器），默认不排除任何。

    策略（优先级从高到低）：
    1. 第一个从未被封禁的 Profile（last_ban_time 为空）
    2. 全部被封禁时，选 last_ban_time 最早且冷却时间已到的
    3. 冷却期未到 → 抛出 NoBrowserAvailableError
    """
    rows = _read_csv(config.BROWSERS_CSV_PATH, _BROWSERS_COLS, required=False)
    if not rows:
        raise NoBrowserAvailableError("browsers.csv 为空，无可用浏览器")

    exclude = exclude or set()
    rows = [r for r in rows if r["profile_id"] not in exclude]
    if not rows:
        raise NoBrowserAvailableError("所有浏览器均已在本轮使用过，无可用浏览器")

    # 优先：从未被封禁的 Profile 中选 last_launch_time 最早的（最久未使用，均衡分担）
    unbanned = [r for r in rows if not r["last_ban_time"]]
    if unbanned:
        best_unbanned = min(unbanned, key=lambda r: r["last_launch_time"] or "")
        logger.info("选中未封禁浏览器: %s (%s)", best_unbanned.get("name", ""), best_unbanned["profile_id"])
        return best_unbanned

    # 全部被封禁 → 找冷却最久的
    def _ban_dt(row: dict) -> datetime:
        try:
            return datetime.strptime(row["last_ban_time"], _FMT)
        except Exception:
            return datetime.max

    best = min(rows, key=_ban_dt)
    ban_dt = _ban_dt(best)
    elapsed = datetime.now() - ban_dt
    min_interval = timedelta(seconds=config.MIN_RETRY_INTERVAL)

    if elapsed >= min_interval:
        logger.info(
            "所有浏览器均被封禁，选冷却最久的: %s (%s)，封禁时长 %s",
            best.get("name", ""), best["profile_id"], elapsed,
        )
        return best

    remaining  = min_interval - elapsed
    total_sec  = int(remaining.total_seconds())
    h, rem     = divmod(total_sec, 3600)
    m, s       = divmod(rem, 60)
    raise NoBrowserAvailableError(
        f"没有一个浏览器符合启动条件。\n"
        f"最符合的浏览器: {best.get('name', '')} ({best['profile_id']})\n"
        f"距离最短重试时间（{config.MIN_RETRY_INTERVAL // 60}min）还差: {h}h {m}m {s}s"
    )


def record_browser_launch(profile_id: str) -> None:
    """记录某个 Profile 的启动时间。"""
    _update_browser_field(profile_id, "last_launch_time", _now())


def record_browser_ban(profile_id: str) -> None:
    """记录某个 Profile 的 IP 封禁时间。"""
    ts = _now()
    _update_browser_field(profile_id, "last_ban_time", ts)
    logger.info("Profile %s IP 封禁时间已记录: %s", profile_id, ts)


def _update_browser_field(profile_id: str, field: str, value: str) -> None:
    rows = _read_csv(config.BROWSERS_CSV_PATH, _BROWSERS_COLS, required=False)
    found = False
    for row in rows:
        if row["profile_id"] == profile_id:
            row[field] = value
            found = True
    if not found:
        logger.warning("browsers.csv 中未找到 Profile: %s，忽略更新", profile_id)
        return
    _write_csv(config.BROWSERS_CSV_PATH, _BROWSERS_COLS, rows)


# ══════════════════════════════════════════════
#   底层 CSV 读写（后续换数据库只改这里）
# ══════════════════════════════════════════════

def _read_csv(path: str, cols: list[str], required: bool = True) -> list[dict]:
    """读取 CSV，自动补齐缺失列，返回 list[dict]。"""
    if not os.path.exists(path):
        if required:
            raise FileNotFoundError(f"文件不存在: {path}")
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = [{col: row.get(col, "") for col in cols} for row in reader]
    return rows


def _write_csv(path: str, cols: list[str], rows: list[dict]) -> None:
    """将 list[dict] 写回 CSV。

    先写到同目录 .tmp 临时文件，成功后再原子替换正式文件，
    防止进程在写入中途被 Ctrl+C 或意外 Kill 导致文件截断/丢失。
    """
    dir_ = os.path.dirname(path) or "."
    os.makedirs(dir_, exist_ok=True)
    tmp = path + ".tmp"
    with _csv_write_lock:
        with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp, path)  # 原子替换：同盘上 rename 是原子操作


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
