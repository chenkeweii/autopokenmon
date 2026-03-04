"""
logger.py —— 日志工具
职责：为每个模块提供统一格式的日志记录器，同时输出到控制台和文件。

多 Worker 支持
--------------
在 Worker 协程开头调用 ``set_worker_id(n)``，该 asyncio Task 内的所有日志
将自动在模块名前插入 ``[W{n}]`` 标签。控制台为每个 Worker 分配独立颜色
（W1=青色 W2=黄色 W3=绿色 W4=洋红 W5=蓝色 W6=亮青色，超出后循环），
文件日志保持纯文本。
"""

from __future__ import annotations

import contextvars
import logging
import os
from datetime import datetime
from typing import Optional

import config

_INITIALIZED = False

# ── Worker 上下文变量 ────────────────────────────────────────────────────────
# asyncio.create_task 会复制当前 Context，所以必须在 Task 内部调用才能隔离。
_worker_id_var: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "_worker_id_var", default=None
)

# 控制台各 Worker 的 ANSI 前景色（按 worker_id - 1 循环取用）
_WORKER_COLORS = [
    "\033[36m",   # W1 - 青色   (Cyan)
    "\033[33m",   # W2 - 黄色   (Yellow)
    "\033[32m",   # W3 - 绿色   (Green)
    "\033[35m",   # W4 - 洋红   (Magenta)
    "\033[34m",   # W5 - 蓝色   (Blue)
    "\033[96m",   # W6 - 亮青色 (Bright Cyan)
]
_RESET = "\033[0m"

# 日志格式：%(worker_tag)s 由 _WorkerFilter 注入，宽 5 字符（[W1]_/[W10]/空白）
_FMT      = "[%(asctime)s] %(levelname)-7s | %(worker_tag)s%(name)-28s | %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"


def set_worker_id(worker_id: int) -> None:
    """
    在 Worker 协程开头调用，之后该 Task 内的所有日志自动带 ``[W{id}]`` 标签。
    必须在 asyncio Task 内部调用（Task 持有独立 Context 副本），勿在创建 Task 前调用。
    """
    _worker_id_var.set(worker_id)


def _ensure_log_dir() -> None:
    os.makedirs(config.LOG_DIR, exist_ok=True)


class _WorkerFilter(logging.Filter):
    """
    向每条 LogRecord 注入两个字段：
      worker_tag        : 纯文本标签，供文件 Handler 使用
      worker_tag_colored: 带 ANSI 色标签，供控制台 Handler 使用
    """

    def filter(self, record: logging.LogRecord) -> bool:
        wid = _worker_id_var.get()
        if wid is None:
            record.worker_tag         = "     "   # 5 空格，与 [W1]_ 等宽
            record.worker_tag_colored = "     "
        else:
            tag = f"[W{wid}]"
            # 右侧补空格至 5 字符（[W1]=4 → 补 1；[W10]=5 → 不补）
            pad                       = " " * max(0, 5 - len(tag))
            color                     = _WORKER_COLORS[(wid - 1) % len(_WORKER_COLORS)]
            record.worker_tag         = tag + pad
            record.worker_tag_colored = f"{color}{tag}{_RESET}{pad}"
        return True


class _ColorFormatter(logging.Formatter):
    """控制台 Handler：将 worker_tag 临时替换为带颜色版本后格式化。"""

    def format(self, record: logging.LogRecord) -> str:
        plain             = record.worker_tag
        record.worker_tag = record.worker_tag_colored
        result            = super().format(record)
        record.worker_tag = plain
        return result


def _setup_root_logger() -> None:
    """首次调用时初始化根日志配置（仅执行一次）。"""
    global _INITIALIZED
    if _INITIALIZED:
        return
    _INITIALIZED = True

    _ensure_log_dir()

    log_file = os.path.join(
        config.LOG_DIR,
        f"run_{datetime.now():%Y%m%d_%H%M%S}.log",
    )

    worker_filter = _WorkerFilter()

    # 文件 Handler（DEBUG+，纯文本，无 ANSI 码）
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(_FMT, datefmt=_DATE_FMT))
    fh.addFilter(worker_filter)

    # 控制台 Handler（INFO+，带颜色）
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(_ColorFormatter(_FMT, datefmt=_DATE_FMT))
    ch.addFilter(worker_filter)

    root = logging.getLogger()
    root.setLevel(getattr(logging, config.LOG_LEVEL, logging.DEBUG))
    root.addHandler(fh)
    root.addHandler(ch)


def get_logger(name: str) -> logging.Logger:
    """
    获取一个具名日志记录器。
    首次调用时自动完成全局日志初始化。

    Parameters
    ----------
    name : str
        通常传入 ``__name__``。

    Returns
    -------
    logging.Logger
    """
    _setup_root_logger()
    return logging.getLogger(name)
