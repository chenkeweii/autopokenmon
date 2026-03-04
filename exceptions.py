"""
自定义异常 —— 统一异常体系，方便上层按类型捕获并记录日志。
"""


class AppBaseError(Exception):
    """所有自定义异常的基类。"""


class BrowserLaunchError(AppBaseError):
    """Nstbrowser Profile 启动失败或 CDP 连接失败。"""


class LoginError(AppBaseError):
    """登录流程异常（凭据错误、页面结构变化等）。"""


class OTPTimeoutError(AppBaseError):
    """在规定时间内未能从邮箱获取验证码。"""


class AppointmentError(AppBaseError):
    """预约流程异常（按钮未找到、确认失败等）。"""


class IPBlockedError(AppBaseError):
    """当前 IP 被目标网站封禁（触发频率限制、验证墙等）。"""


class NoBrowserAvailableError(AppBaseError):
    """所有 Profile 均在 IP 封禁冷却期内，暂时无可用浏览器。"""


class AccountNeedsResetError(AppBaseError):
    """账号需要重置密码（日文站点提示「エラーが発生しました」等），该账号直接标 status=2，
    不计入 IP 封禁连续失败计数。"""
