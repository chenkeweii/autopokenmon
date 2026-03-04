"""
email_fetcher.py -- IMAP 邮件等待模块

公开接口：
  start_idle_monitor(email_addr, auth_code)
      → 返回 asyncio.Task，在后台线程持续 IDLE 监听。
        OTP 邮件写入 data/emails.csv + 广播唤醒所有等待方；
        预约确认邮件写入 _recent_confirms + 广播唤醒所有等待者。

  wait_for_new_email_since(since_ts, timeout_seconds, recipient)
      → 异步等待 OTP 邮件，Step 5 调用此接口。

  wait_for_appointment_confirm(since_ts, recipient, timeout_seconds)
      → 异步等待预约确认邮件（応募完了のお知らせ）。
        采用广播唤醒设计，多账号并发等待时各自扱扫 _recent_confirms，
        不存在等待方互相抢占邮件的问题。

  stop_idle_monitor()
      → 通知后台线程停止。
"""

from __future__ import annotations

import collections
import csv
import os
import re
import threading
import time
import asyncio
from datetime import datetime
from email import message_from_bytes
from email.header import decode_header

from imapclient import IMAPClient

from utils.logger import get_logger
import config

logger = get_logger(__name__)

_EMAILS_CSV_PATH = config.EMAILS_CSV_PATH
# 列说明：
#   original_sent_at     = 发件人发出时间（邮件 Date 头 / 转发体中的发件时间）
#   original_received_at = 服务器实际收信时间（IMAP INTERNALDATE）
#   original_from        = 原始发件人
#   original_to          = 原始收件人
#   otp_code             = 验证码
_EMAILS_COLS = ["original_sent_at", "original_received_at", "original_from", "original_to", "otp_code"]

# IDLE 每个周期最长秒数（到期后 DONE + 重新进 IDLE，防 NAT 超时）
_IDLE_CYCLE_SECONDS = 25
# idle_check 每次最多等待秒数
_IDLE_CHUNK_SECONDS = 5

_IMAP_SERVER_MAP = {
    "qq.com":      "imap.qq.com",
    "foxmail.com": "imap.qq.com",
    "gmail.com":   "imap.gmail.com",
    "163.com":     "imap.163.com",
    "126.com":     "imap.126.com",
    "outlook.com": "imap-mail.outlook.com",
    "hotmail.com": "imap-mail.outlook.com",
}

# ──────────────────────────────────────────────
# 后台持续监听接口
# ──────────────────────────────────────────────

_stop_event: threading.Event = threading.Event()
_monitor_task: asyncio.Task | None = None
# OTP 邮件缓存（最夐50封）+ 广播唤醒：某 Worker 不会“抜走”其他 Worker 的验证码邮件
_recent_otps: collections.deque = collections.deque(maxlen=50)
_otp_waiters: list = []              # list[asyncio.Event]
# 近期确认邮件缓存（最夐50封），防止邮件在 wait 调用前已到达被漏掉
_recent_confirms: collections.deque = collections.deque(maxlen=50)
_confirm_waiters: list = []          # list[asyncio.Event]
_event_loop: asyncio.AbstractEventLoop | None = None


def _otp_put(mail_dict: dict) -> None:
    """从任意线程安全地写入 OTP 缓存，并广播唤醒所有正在等待 OTP 的协程。"""
    _recent_otps.append(mail_dict)  # deque.append 在 CPython 中是线程安全的
    if _event_loop:
        def _wakeup_all():
            for ev in _otp_waiters:
                ev.set()
        _event_loop.call_soon_threadsafe(_wakeup_all)


def _appoint_put(mail_dict: dict) -> None:
    """从任意线程安全地写入近期缓存，并广播唤醒所有正在等待确认邮件的协程。"""
    _recent_confirms.append(mail_dict)  # deque.append 在 CPython 中是线程安全的
    if _event_loop:
        def _wakeup_all():
            for ev in _confirm_waiters:
                ev.set()
        _event_loop.call_soon_threadsafe(_wakeup_all)


def start_idle_monitor(email_addr: str, auth_code: str) -> asyncio.Task:
    """
    启动后台 IDLE 监听，立即返回 asyncio.Task。
    新邮件到达时自动写入 data/emails.csv，同时推送到内存 Queue 供即时唤醒。
    调用 stop_idle_monitor() 停止。
    """
    global _stop_event, _monitor_task, _event_loop
    _stop_event.clear()
    _event_loop = asyncio.get_running_loop()
    start_ts = time.time()  # 记录启动时刻，传给线程做 catch-up
    _monitor_task = asyncio.create_task(
        asyncio.to_thread(_blocking_idle_monitor_loop, email_addr, auth_code, _stop_event, start_ts)
    )
    return _monitor_task


def stop_idle_monitor() -> None:
    """通知后台监听线程停止。"""
    _stop_event.set()


async def wait_for_new_email_since(
    since_ts: float,
    timeout_seconds: int = 180,
    recipient: str = "",
) -> dict | None:
    """
    等待符合条件的 OTP 邮件（广播唤醒模型，与 wait_for_appointment_confirm 对称）：
      - IMAP INTERNALDATE > since_ts（since_ts 应为点击登录按钮的时刻）
      - original_to 包含 recipient

    多 Worker 并发等待时，各协程注册私有 asyncio.Event，邮件到达时全部广播唤醒，
    各自独立扫描 _recent_otps 缓存，不存在「某 Worker 抢走其他 Worker 的验证码」的问题。
    同时保留 CSV 兜底，防止极少数情况下缓存漏掉邮件。
    """
    if _event_loop is None:
        logger.warning("wait_for_new_email_since: IDLE 监听未启动，跳过 OTP 等待")
        return None

    logger.info("等待验证码邮件（最多 %d 秒，收件人=%s）...", timeout_seconds, recipient)

    # ── 0. 先扫缓存（邮件可能在此函数调用前就已到达）──
    for m in reversed(list(_recent_otps)):
        if _mail_matches(m, since_ts, recipient):
            _log_got_mail(m)
            return m

    # ── 1. 查 CSV 兜底（catch-up 写入但未进内存缓存的极端情况）──
    entry = _read_latest_csv_entry_after(since_ts, recipient)
    if entry:
        _log_got_mail(entry)
        return entry

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        wake_ev = asyncio.Event()
        _otp_waiters.append(wake_ev)
        # 注册后再扫一次缓存，消除「刚注册前邮件已到」的竞争窗口
        for m in reversed(list(_recent_otps)):
            if _mail_matches(m, since_ts, recipient):
                _otp_waiters.remove(wake_ev)
                _log_got_mail(m)
                return m

        remaining = deadline - time.time()
        try:
            await asyncio.wait_for(wake_ev.wait(), timeout=min(5.0, remaining))
        except asyncio.TimeoutError:
            pass
        finally:
            try:
                _otp_waiters.remove(wake_ev)
            except ValueError:
                pass

        # 唤醒或超时后扫缓存
        for m in reversed(list(_recent_otps)):
            if _mail_matches(m, since_ts, recipient):
                _log_got_mail(m)
                return m

        # CSV 兜底
        entry = _read_latest_csv_entry_after(since_ts, recipient)
        if entry:
            _log_got_mail(entry)
            return entry

        logger.debug("仍在等待验证码邮件（收件人=%s，剩余 %.0fs）...",
                     recipient, deadline - time.time())

    logger.warning("等待邮件超时（%d 秒），收件人=%s", timeout_seconds, recipient)
    return None


async def wait_for_appointment_confirm(
    since_ts: float,
    recipient: str,
    timeout_seconds: int = 90,
) -> dict | None:
    """
    等待目标账号的预约确认邮件（応募完了のお知らせ）。

    采用广播唤醒设计：每个调用协程注册一个私有 asyncio.Event，
    邮件到达时 _appoint_put 同时 set 所有等待者的 Event。
    各协程独立扫描 _recent_confirms，互不干扰，并发安全。

    参数
    ----
    since_ts  : 点击「応募する」按钮的 Unix 时刻（过滤更早的邮件）
    recipient : 账号邮箱地址（即 accounts.csv 中的 username）
    Returns dict（含 original_to / original_received_at 等）或 None（超时）
    """
    if _event_loop is None:
        logger.warning("wait_for_appointment_confirm: IDLE 监听未启动，跳过邮件确认")
        return None

    logger.info("等待预约确认邮件（最多 %d 秒，收件人=%s）...", timeout_seconds, recipient)

    # ── 0. 先扫近期缓存（邮件可能在此函数调用前就已到达）──
    for m in reversed(list(_recent_confirms)):
        if _mail_matches(m, since_ts, recipient):
            logger.info("[Step 11] ✓ 缓存命中预约确认邮件 | to=%s | received=%s",
                        m.get("original_to", "-"), m.get("original_received_at", "-"))
            return m

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        # 注册私有唤醒 Event，放入全局列表
        wake_ev = asyncio.Event()
        _confirm_waiters.append(wake_ev)
        # 注册后再扫一次缓存，防止「刚注册前邮件已到」的竞争窗口
        for m in reversed(list(_recent_confirms)):
            if _mail_matches(m, since_ts, recipient):
                _confirm_waiters.remove(wake_ev)
                logger.info("[Step 11] ✓ 注册后缓存命中 | to=%s | received=%s",
                            m.get("original_to", "-"), m.get("original_received_at", "-"))
                return m

        remaining = deadline - time.time()
        try:
            await asyncio.wait_for(wake_ev.wait(), timeout=min(5.0, remaining))
        except asyncio.TimeoutError:
            pass
        finally:
            # 无论超时还是被唤醒，都从列表移除，防止内存泄漏
            try:
                _confirm_waiters.remove(wake_ev)
            except ValueError:
                pass

        # 唤醒或超时后扫缓存
        for m in reversed(list(_recent_confirms)):
            if _mail_matches(m, since_ts, recipient):
                logger.info(
                    "[Step 11] ✓ 收到预约确认邮件 | to=%s | received=%s | subject=%s",
                    m.get("original_to", "-"),
                    m.get("original_received_at", "-"),
                    m.get("subject", "-"),
                )
                return m

        logger.debug("仍在等待预约确认邮件（收件人=%s，剩余 %.0fs）...",
                     recipient, deadline - time.time())

    logger.warning("等待预约确认邮件超时（%d 秒），收件人=%s", timeout_seconds, recipient)
    return None


def _mail_matches(mail: dict, since_ts: float, recipient: str) -> bool:
    """检查邮件是否满足时间和收件人条件。"""
    try:
        recv_ts = datetime.strptime(
            mail["original_received_at"], "%Y-%m-%d %H:%M:%S"
        ).timestamp()
        if recv_ts <= since_ts:
            return False
    except Exception:
        pass
    if recipient and recipient.lower() not in mail.get("original_to", "").lower():
        return False
    return True


def _log_got_mail(mail: dict) -> None:
    logger.info(
        "[Step 5] ✓ 收到验证码邮件 → otp: %s | to: %s | received: %s | from: %s",
        mail.get("otp_code", "-"),
        mail.get("original_to", "-"),
        mail.get("original_received_at", "-"),
        mail.get("original_from", "-"),
    )


def _blocking_idle_monitor_loop(
    email_addr: str,
    auth_code: str,
    stop_event: threading.Event,
    start_ts: float = 0.0,
) -> None:
    """
    在独立线程中持续 IDLE 监听，直到 stop_event 被设置。
    start_ts: 线程启动时刻，将对比该时刻序号范围内的旧邮件做 catch-up。
    """
    server = _resolve_imap_server(email_addr)
    logger.info("[监听线程] 启动，连接 %s:993", server)

    while not stop_event.is_set():
        client = None
        try:
            client = IMAPClient(server, port=993, ssl=True, use_uid=False)
            client.login(email_addr, auth_code)
            client.select_folder("INBOX")

            status = client.folder_status("INBOX", ["MESSAGES"])
            known_count = status[b"MESSAGES"]
            logger.info("[监听线程] INBOX 邮件数: %d，进入 IDLE 循环", known_count)

            # ── Catch-up：检查最近 5 封，仅写入 INTERNALDATE > start_ts 的邮件 ──
            # 这样确保「程序启动之前」就已存在的旧邮件不会被误写入 CSV。
            if known_count > 0:
                check_ids = list(range(max(1, known_count - 4), known_count + 1))
                try:
                    catchup_msgs = client.fetch(check_ids, [b"RFC822", b"INTERNALDATE"])
                    for seq, data in catchup_msgs.items():
                        raw          = data.get(b"RFC822")
                        internaldate = data.get(b"INTERNALDATE")  # datetime (UTC, tz-aware)
                        if not raw:
                            continue
                        # 服务器收信时间早于监听启动时刻 → 旧邮件，跳过
                        if internaldate and internaldate.timestamp() <= start_ts:
                            logger.debug("[监听线程] Catch-up 跳过旧邮件 seq=%s internaldate=%s", seq, internaldate)
                            continue
                        mail_dict = _parse_pokemon_email(raw, internaldate)
                        if not mail_dict:
                            continue
                        email_type = mail_dict.get("email_type", "other")
                        if email_type == "otp":
                            if _email_already_in_csv(mail_dict["original_received_at"], mail_dict["original_to"]):
                                logger.debug("[监听线程] Catch-up 跳过重复OTP received=%s to=%s", mail_dict["original_received_at"], mail_dict["original_to"])
                                continue
                            _append_to_csv(mail_dict)
                            _otp_put(mail_dict)
                            logger.info(
                                "[监听线程] Catch-up OTP写入CSV | otp=%s | to=%s | received=%s",
                                mail_dict["otp_code"], mail_dict["original_to"],
                                mail_dict["original_received_at"],
                            )
                        elif email_type == "confirm":
                            _appoint_put(mail_dict)
                            logger.info(
                                "[监听线程] Catch-up 预约确认邮件 | to=%s | subject=%s",
                                mail_dict["original_to"], mail_dict.get("subject", ""),
                            )
                        else:
                            logger.debug("[监听线程] Catch-up 跳过非目标邮件 to=%s", mail_dict.get("original_to", ""))
                except Exception as e:
                    logger.warning("[监听线程] Catch-up 失败: %s", e)

            while not stop_event.is_set():
                cycle_end = time.time() + _IDLE_CYCLE_SECONDS
                client.idle()
                got_push = False

                while time.time() < cycle_end and not stop_event.is_set():
                    chunk = min(_IDLE_CHUNK_SECONDS, cycle_end - time.time())
                    if chunk <= 0:
                        break
                    responses = client.idle_check(timeout=chunk)
                    if responses:
                        logger.debug("[监听线程] IDLE 推送: %s", responses)
                        got_push = True
                        break

                client.idle_done()
                if stop_event.is_set():
                    break

                cur_status = client.folder_status("INBOX", ["MESSAGES"])
                cur_count = cur_status[b"MESSAGES"]

                if cur_count > known_count:
                    logger.info(
                        "[监听线程] 新邮件到达：%d -> %d（IDLE推送=%s）",
                        known_count, cur_count, got_push,
                    )
                    fetch_ids = list(range(known_count + 1, cur_count + 1))
                    time.sleep(0.5)
                    messages = client.fetch(fetch_ids, [b"RFC822", b"INTERNALDATE"])
                    logger.info("[监听线程] FETCH 返回 %d 封", len(messages))
                    for seq, data in messages.items():
                        raw          = data.get(b"RFC822")
                        internaldate = data.get(b"INTERNALDATE")
                        if not raw:
                            logger.warning("[监听线程] 序号=%s 无 RFC822 数据", seq)
                            continue
                        mail_dict = _parse_pokemon_email(raw, internaldate)
                        if not mail_dict:
                            logger.warning("[监听线程] 序号=%s 邮件解析失败", seq)
                            continue
                        email_type = mail_dict.get("email_type", "other")
                        if email_type == "otp":
                            if _email_already_in_csv(mail_dict["original_received_at"], mail_dict["original_to"]):
                                logger.debug("[监听线程] 跳过重复OTP seq=%s to=%s", seq, mail_dict["original_to"])
                            else:
                                _append_to_csv(mail_dict)
                                _otp_put(mail_dict)
                                logger.info(
                                    "[监听线程] OTP写入CSV | from=%s | to=%s | otp=%s | received=%s",
                                    mail_dict["original_from"], mail_dict["original_to"],
                                    mail_dict["otp_code"], mail_dict["original_received_at"],
                                )
                        elif email_type == "confirm":
                            _appoint_put(mail_dict)
                            logger.info(
                                "[监听线程] 预约确认邮件 | from=%s | to=%s | received=%s",
                                mail_dict["original_from"], mail_dict["original_to"],
                                mail_dict["original_received_at"],
                            )
                        else:
                            logger.debug("[监听线程] 非目标邮件 seq=%s to=%s", seq, mail_dict.get("original_to", ""))
                    known_count = cur_count

        except Exception as exc:
            if stop_event.is_set():
                break
            logger.warning("[监听线程] 连接异常: %s，5 秒后重连...", exc, exc_info=True)
            time.sleep(5)
        finally:
            if client:
                try:
                    client.logout()
                except Exception:
                    pass

    logger.info("[监听线程] 已停止")


def _parse_pokemon_email(raw: bytes, internaldate=None) -> dict | None:
    """
    解析 Pokemon Center OTP 邮件（含转发场景）。
    提取：
      - original_sent_at     原始发件时间（邮件 Date 头 / 转发体中的发件时间：行）
      - original_received_at 服务器收信时间（IMAP INTERNALDATE，即该邮件何时到达 QQ 邮箱）
      - original_from        原始发件人
      - original_to          原始收件人
      - otp_code             从主题或正文提取的验证码
    internaldate: imapclient 返回的 datetime（UTC, tz-aware），可为 None。
    """
    try:
        msg = message_from_bytes(raw)
        subject = _decode_header_str(msg.get("Subject", ""))
        body    = _extract_body(msg)

        # ── 1. 尝试从转发正文中提取原始字段 ──────────────────────────
        # QQ/Foxmail 转发格式：
        #   -------- 转发邮件信息 --------
        #   发件人："xxx" <xxx@xxx.com>
        #   收件人：yyy@yyy.com
        #   发件时间：2026年2月23日 15:41
        fw_from  = re.search(r'发件人[：:]\s*(?:"[^"]*"\s*)?<?([^>\n\r]+)>?', body)
        fw_to    = re.search(r'收件人[：:]\s*([^\n\r]+)', body)
        fw_date  = re.search(r'发件时间[：:]\s*([^\n\r]+)', body)

        original_from     = fw_from.group(1).strip()  if fw_from  else _decode_header_str(msg.get("From", ""))
        original_to       = fw_to.group(1).strip()    if fw_to    else _decode_header_str(msg.get("To",   ""))
        original_sent_at  = fw_date.group(1).strip()  if fw_date  else _decode_header_str(msg.get("Date", ""))

        # INTERNALDATE → 本地时间字符串
        if internaldate is not None:
            try:
                original_received_at = internaldate.astimezone().strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                original_received_at = str(internaldate)
        else:
            original_received_at = _now_str()

        # 如果发件人行含引号格式："ポケモンセンター" <info@...>，只取尖括号内地址
        addr_in_brackets = re.search(r'<([^>]+)>', original_from)
        if addr_in_brackets:
            original_from_addr = addr_in_brackets.group(1).strip()
            # 保留显示名 + 地址
            display = re.sub(r'<[^>]+>', '', original_from).strip().strip('"').strip()
            original_from = f'{display} <{original_from_addr}>' if display else original_from_addr

        # ── 2. 识别邮件类型 ───────────────────────────────────────────
        # 类型1：预约确认   Subject 包含「応募完了のお知らせ」
        # 类型2：OTP 验证码  Subject/Body 包含「パスコード」数字
        # 类型3：其他（跳过）
        is_confirm = "応募完了のお知らせ" in subject

        otp_match = (
            re.search(r'【パスコード】(\d{4,8})', subject + body)
            or re.search(r'パスコード[：:]\s*(\d{4,8})', subject + body)
            or re.search(r'(?:code|CODE|Code)[\s：:]+([A-Z0-9]{4,8})', subject + body)
        )
        otp_code = otp_match.group(1) if otp_match else ""

        if is_confirm:
            email_type = "confirm"
            # 确认邮件中，glowinow.com 转发时把原始账号地址写入 Sender: 头
            # （To: 里是编码后的转发信封地址，无法直接匹配 accounts.csv 里的用户名）
            # 例：Sender: allengo@glowinow.com  ← 这才是账号邮箱
            sender_raw = _decode_header_str(msg.get("Sender", ""))
            if sender_raw:
                # 取尖括号内地址，或整个字段
                m = re.search(r'<([^>]+)>', sender_raw)
                original_to = m.group(1).strip() if m else sender_raw.strip()
        elif otp_code:
            email_type = "otp"
        else:
            email_type = "other"

        return {
            "email_type":           email_type,
            "subject":              subject,
            "original_sent_at":     original_sent_at,
            "original_received_at": original_received_at,
            "original_from":        original_from,
            "original_to":          original_to,
            "otp_code":             otp_code,
        }
    except Exception as exc:
        logger.warning("邮件解析失败: %s", exc)
        return None


def _resolve_imap_server(email_addr: str) -> str:
    domain = email_addr.split("@")[-1].lower()
    server = _IMAP_SERVER_MAP.get(domain)
    if not server:
        server = f"imap.{domain}"
        logger.warning("未知域名 '%s'，使用默认服务器: %s", domain, server)
    return server


def _decode_header_str(value: str) -> str:
    parts = decode_header(value)
    result = []
    for part, enc in parts:
        if isinstance(part, bytes):
            result.append(part.decode(enc or "utf-8", errors="ignore"))
        else:
            result.append(str(part))
    return "".join(result)


def _extract_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                charset = part.get_content_charset() or "utf-8"
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(charset, errors="ignore")
    else:
        charset = msg.get_content_charset() or "utf-8"
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode(charset, errors="ignore")
    return ""


def _email_already_in_csv(original_received_at: str, original_to: str) -> bool:
    """
    CSV 中是否已有相同 (original_received_at, original_to) 的记录。
    复合键查重：INTERNALDATE 精确到秒，多账号并发时同一秒可能有不同收件人的邮件，
    加上 original_to 后两者同时相同才算重复，避免误判。
    """
    path = _EMAILS_CSV_PATH
    if not os.path.exists(path):
        return False
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if (row.get("original_received_at") == original_received_at
                        and row.get("original_to") == original_to):
                    return True
    except Exception:
        pass
    return False


def _append_to_csv(mail_dict: dict) -> None:
    path = _EMAILS_CSV_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    file_exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=_EMAILS_COLS, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerow(mail_dict)


def _read_latest_csv_entry_after(since_ts: float, recipient: str = "") -> dict | None:
    """
    读取 CSV 中 original_received_at > since_ts、且 original_to 包含 recipient 的最新一行。
    since_ts 应为「点击登录按钮」的时刻（Unix timestamp）。
    """
    path = _EMAILS_CSV_PATH
    if not os.path.exists(path):
        return None
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        for row in reversed(rows):
            try:
                row_ts = datetime.strptime(row["original_received_at"], "%Y-%m-%d %H:%M:%S").timestamp()
                if row_ts <= since_ts:
                    continue
                if recipient and recipient.lower() not in row.get("original_to", "").lower():
                    continue
                return dict(row)
            except Exception:
                continue
    except Exception:
        pass
    return None


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")