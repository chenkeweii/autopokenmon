"""
notifier.py —— 程序状态邮件通知
职责：在程序正常结束、异常退出等关键时刻，通过 SMTP 发送通知邮件。

发件账号复用 OTP 邮箱（OTP_EMAIL_ADDR + OTP_EMAIL_AUTH_CODE），
收件地址由 NOTIFY_TO_EMAIL 单独配置。
调用方只需调用 send_notify(subject, body)，失败会记录日志但不抛异常。
"""

from __future__ import annotations

import smtplib
import socket
from datetime import datetime
from email.mime.text import MIMEText

import config
from utils.logger import get_logger

logger = get_logger(__name__)

_SMTP_SERVER_MAP = {
    "qq.com":      ("smtp.qq.com",      465),
    "foxmail.com": ("smtp.qq.com",      465),
    "gmail.com":   ("smtp.gmail.com",   465),
    "163.com":     ("smtp.163.com",     465),
    "126.com":     ("smtp.126.com",     465),
    "outlook.com": ("smtp.office365.com", 587),
    "hotmail.com": ("smtp.office365.com", 587),
}


def send_notify(subject: str, body: str) -> bool:
    """
    发送通知邮件。不抛异常，失败返回 False 并记录日志。

    subject : 邮件主题
    body    : 纯文本正文
    返回    : True=发送成功，False=未启用或发送失败
    """
    if not config.NOTIFY_ENABLED:
        return False

    from_addr = config.OTP_EMAIL_ADDR
    to_addr   = config.NOTIFY_TO_EMAIL
    auth_code = config.OTP_EMAIL_AUTH_CODE

    domain = from_addr.split("@")[-1].lower()
    smtp_host, smtp_port = _SMTP_SERVER_MAP.get(domain, (f"smtp.{domain}", 465))

    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full_body = f"[{timestamp}]\n\n{body}"

        msg = MIMEText(full_body, "plain", "utf-8")
        msg["Subject"] = f"[Pokemon Bot] {subject}"
        msg["From"]    = from_addr
        msg["To"]      = to_addr

        use_starttls = smtp_port == 587
        if use_starttls:
            smtp = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
            smtp.starttls()
        else:
            smtp = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15)

        smtp.login(from_addr, auth_code)
        smtp.sendmail(from_addr, [to_addr], msg.as_string())
        smtp.quit()

        logger.info("[通知] 邮件已发送 → %s | 主题: %s", to_addr, subject)
        return True

    except (smtplib.SMTPException, socket.error, OSError) as exc:
        logger.warning("[通知] 邮件发送失败: %s", exc)
        return False
