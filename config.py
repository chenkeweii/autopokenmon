"""
全局配置 —— 所有可调参数集中在此。
注意：此文件只存「参数」，不存「数据」。
    参数  → config.py     （这里）
    账号数据 → data/accounts.csv
    浏览器数据 → data/browsers.csv
    邮箱内容 → data/emails.csv
"""

# ──────────────────────── Nstbrowser API (v2) ────────────────────────
NST_HOST   = "localhost:8848"
NST_API_KEY = "15fd6cab-f7f9-4ce2-8e4c-251ff2133e57"

# ──────────────────────── 批量创建环境（setup_profiles.py 用）────────────────────
# 有多少个端口就创建多少个 Profile，每个 Profile 绑定一个唯一的 socks5 代理
PROXY_PROTOCOL   = "socks5"     # 代理协议：socks5 / http / https
PROXY_HOST       = "1.2.3.4"   # 代理服务器 IP 或域名
PROXY_PORT_START = 20000        # 端口范围起始（含）
PROXY_PORT_END   = 20005        # 端口范围结束（含）
PROXY_USERNAME   = ""           # 代理用户名（无认证则留空）
PROXY_PASSWORD   = ""           # 代理密码（无认证则留空）

PROFILE_NAME_PREFIX = "test"     # 创建的 Profile 名称前缀，结果如 NST_1, NST_2 ...
PROFILE_GROUP_NAME  = "test" # 创建到哪个 Nstbrowser 分组

# ──────────────────────────── 目标网站 ────────────────────────────────────────
POKEMON_HOME_URL        = "https://www.pokemoncenter-online.com/"               # 主页（流程起点）
MYPAGE_URL              = "https://www.pokemoncenter-online.com/mypage/"         # 登录后自动跳转至此；navigate_to_lottery 用于保底确认
POKEMON_APPOINTMENT_URL = "https://www.pokemoncenter-online.com/lottery/apply.html"  # 调试模式 goto & 超时重试 goto 用

# ──────────────────────────── 并发控制 ────────────────────────────────────────
# 同时启动几条完整流水线（每条流水线 = 一个独立指纹浏览器 + 一批账号顺序处理）。
# 1 = 单线程（原始行为，最保险）
# N = N 个浏览器并行跑，账号按轮询分配给各 Worker，速度近似提升 N 倍。
# 前提：至少配置了 N 个不同 Profile（即 N 个不同代理 IP）。
# 建议：有几个可用 Profile 就设几；不要超过 Profile 数量，超出部分会因无可用浏览器而失败。
CONCURRENT_BROWSERS = 1

# ──────────────────────────── IP 封禁重试 ────────────────────────────────────
MIN_RETRY_INTERVAL       = 3600        # IP 被封后最短重试间隔（秒），默认 1 小时
IP_BAN_CONFIRM_THRESHOLD = 2           # 累计成功预约几个账号后才启用「疑似封IP」检测
                                       # 低于此值的连续失败直接标 status=2（视为账号自身问题）
                                       # 达到此值后：首次失败暂存待裁决，再次失败→确认封IP
CLOSE_BROWSER_ON_IP_BAN  = False        # 封IP后是否自动关闭当前指纹浏览器（False 则保持打开）

# ──────────────────────────── 超时 ──────────────────────────────────────────
PAGE_LOAD_TIMEOUT    = 60              # 页面加载超时（秒）
ELEMENT_WAIT_TIMEOUT = 15             # 等待元素出现超时（秒）
# 毫秒版本，直接用于 Playwright API（避免各处反复 * 1000）
PAGE_LOAD_TIMEOUT_MS    = PAGE_LOAD_TIMEOUT    * 1000
ELEMENT_WAIT_TIMEOUT_MS = ELEMENT_WAIT_TIMEOUT * 1000
APPOINT_RETRY_TIMES  = 2              # 预约步骤超时后最多重试几次（重加载页面后重试）
                                       # 总尝试次数 = 1 + APPOINT_RETRY_TIMES
APPOINT_RETRY_WAIT   = 60             # 每次重试前等待的时间（秒），给网络恢复留出余地

# ──────────────────────────── 人类行为仿真参数 ────────────────────────────────
MOUSE_MOVE_STEPS_RANGE       = (15, 35)    # 鼠标移动分几步完成
MOUSE_CORRECTION_STEPS_RANGE = (3, 8)      # human_click 第二段精准修正的步数
CLICK_DELAY_RANGE            = (0.3, 1.2)  # 点击前定准停顿（秒）
CLICK_PRESS_DURATION_RANGE   = (0.05, 0.20) # mousedown 到 mouseup 的按压时长（秒）
MOUSE_CORRECTION_PAUSE_RANGE = (0.05, 0.15) # 两段鼠标移动之间的微停顿（秒）
TYPING_DELAY_RANGE        = (0.05, 0.18) # 逐字打字间隔（秒）
TYPING_THINK_PAUSE_RANGE  = (0.2, 0.6)  # 打字时偶尔停顿思考的额外时长（秒）
ACTION_INTERVAL_RANGE     = (1.0, 3.0)  # 两个业务动作之间的间隔（秒）
SCROLL_PIXELS_RANGE       = (100, 400)  # 随机滚动的像素范围
SCROLL_SETTLE_RANGE       = (0.3, 0.8)  # 滚动后等待页面稳定的时间（秒）
MOUSE_WANDER_PAUSE_RANGE  = (0.1, 0.4)  # random_mouse_wander 每次移动后的停顿（秒）

# ──────────────────────────── 邮箱 OTP 配置 ───────────────────────────────────
# 所有账号的验证码邮件均转发到此统一收件筱
OTP_EMAIL_ADDR     = "842145615@qq.com"   # 收验证码转发的统一邮筱
OTP_EMAIL_AUTH_CODE = "zqjoifrnxszubbhj"       # 该邮筱的 IMAP 授权码
EMAIL_OTP_WAIT = 180                   # 登录后等待验证码邮件的最长时间（秒）
REQUIRE_APPOINT_EMAIL = False          # 预约后是否等收到「応募完了」确认邮件才判定成功
                                       # True  → 必须收到邮件才标 status=1，否则抛 AppointmentError
                                       # False → 点完确认弹窗即视为成功（调试 / 无 IDLE 监听时用）
APPOINT_CONFIRM_WAIT  = 90            # 等待预约确认邮件的最长时间（秒）

# ─────────────────────────── 程序状态通知 ────────────────────────────
# 程序正常运行完成、异常退出、错误等情况下发送通知邮件到指定邮笱。
# 发件账号复用 OTP_EMAIL_ADDR / OTP_EMAIL_AUTH_CODE，SMTP 自动根据域名匹配。
NOTIFY_ENABLED  = True                # False 则全局关闭通知
NOTIFY_TO_EMAIL = "18090672798@163.com"  # 接收通知的邮笱（可与 OTP 收件笱相同）

# 本地调试页面基准路径（动态计算，相对于 config.py 所在目录，不依赖机器路径）
import os as _os
_TESTPAGES_BASE = (
    "file:///"
    + _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "testpages", "")
    .replace("\\", "/")
)

# 本地保存的验证码输入页（开发调试用，真实环境中登录后浏览器会自动跳转到此页）
PASSCODE_PAGE_LOCAL_URL = (
    _TESTPAGES_BASE
    + "%E3%83%91%E3%82%B9%E3%82%B3%E3%83%BC%E3%83%89%E5%85%A5%E5%8A%9B"
    "%EF%BD%9C%E3%80%90%E5%85%AC%E5%BC%8F%E3%80%91%E3%83%9D%E3%82%B1"
    "%E3%83%A2%E3%83%B3%E3%82%BB%E3%83%B3%E3%82%BF%E3%83%BC%E3%82%AA"
    "%E3%83%B3%E3%83%A9%E3%82%A4%E3%83%B3.html"
)

# 本地保存的利用规约再同意页（登录后偶尔出现，需勾选两个复选框才能继续）
TERMS_PAGE_LOCAL_URL = (
    _TESTPAGES_BASE
    + "%E5%88%A9%E7%94%A8%E8%A6%8F%E7%B4%84%E5%86%8D%E5%90%8C%E6%84%8F"
    "%EF%BD%9C%E3%80%90%E5%85%AC%E5%BC%8F%E3%80%91%E3%83%9D%E3%82%B1"
    "%E3%83%A2%E3%83%B3%E3%82%BB%E3%83%B3%E3%82%BF%E3%83%BC%E3%82%AA"
    "%E3%83%B3%E3%83%A9%E3%82%A4%E3%83%B3.htm"
)

# ── 本地调试开关 ──────────────────────────────────────────────────────────────

# 控制1：是否真实点击登录按钮
#   True  → 找到登录按钮并点击，然后检测登录结果（生产流程）
#   False → 填完账密后不点击登录（开发调试，规避登录限制）
DO_CLICK_LOGIN = True

# 控制2：是否模拟登录报错页（仅 DO_CLICK_LOGIN=False 时生效）
#   True  → 加载本地报错页 → 检测红字 → 写入 CSV → 停止
#   False → 不加载报错页，直接往后续步骤执行
SIMULATE_LOGIN_ERROR_PAGE = False

# 切换报错页编号（1 / 2 / 3），仅 SIMULATE_LOGIN_ERROR_PAGE=True 时生效：
#   1 → reCAPTCHAの認証に失敗しました
#   2 → メールアドレスまたはパスワードが一致しませんでした
#   3 → 認証に失敗しました。もう一度操作を行ってください
#   エラーが発生しました。時間をおいてから再度お試しください。
# 
LOGIN_ERROR_TEST_NUM = 1

# 控制3：是否执行验证码流程（Steps 5-7）
#   True  → 正常走：跳转验证码页 → 等邮件 → 填验证码 → 点确认
#   False → 跳过验证码流程，直接进入 Step 9（预约操作）
REQUIRE_OTP = True

# 点击验证码确认后：是否模拟出现利用规约再同意页
#   True  → 跳转到本地利用规约页（测试有合约页分支）
#   False → 不跳转（测试无合约页分支）
SIMULATE_TERMS_PAGE = False

# 模拟封IP测试：从第 N 个账号（1-based）起强制触发登录失败
#   0     → 不模拟（正常流程）
#   N > 0 → 第 N 个及之后的账号跳过真实登录，直接抛 LoginError
#
#   注意：封IP检测需要 success_count 先达到 IP_BAN_CONFIRM_THRESHOLD，所以：
#   要测试封IP检测流程，此值必须 > IP_BAN_CONFIRM_THRESHOLD
#
#   示例（IP_BAN_CONFIRM_THRESHOLD=2）：
#     此值设 3 → acc1✔ acc2✔(success_count=2)，acc3失败待裁决，acc4失败→判定封IP ←推荐测试值
#     此值设 1 → 所有账号 success_count=0 < 2，就是奠标 status=2，不会触发封IP检测
SIMULATE_IP_BAN_FROM_ACCOUNT = 0

MYPAGE_LOCAL_URL = (
    _TESTPAGES_BASE
    + "%E3%83%9E%E3%82%A4%E3%83%9A%E3%83%BC%E3%82%B8%EF%BD%9C%E3%80%90%E5%85%AC%E5%BC%8F%E3%80%91"
    "%E3%83%9D%E3%82%B1%E3%83%A2%E3%83%B3%E3%82%BB%E3%83%B3%E3%82%BF%E3%83%BC%E3%82%AA%E3%83%B3%E3%83%A9%E3%82%A4%E3%83%B3.htm"
)
APPOINTMENT_LOCAL_URL = (
    _TESTPAGES_BASE
    + "%E6%8A%BD%E9%81%B8%E5%BF%9C%E5%8B%9F%E4%B8%80%E8%A6%A7%EF%BD%9C%E3%80%90%E5%85%AC%E5%BC%8F%E3%80%91"
    "%E3%83%9D%E3%82%B1%E3%83%A2%E3%83%B3%E3%82%BB%E3%83%B3%E3%82%BF%E3%83%BC%E3%82%AA%E3%83%B3%E3%83%A9%E3%82%A4%E3%83%B32.htm"
)  # 调试用合并页：列表+展开详情+提交弹窗均在同一页
LOGIN_ERROR_TEST_URL = {
    1: (
        _TESTPAGES_BASE
        + "%E3%83%AD%E3%82%B0%E3%82%A4%E3%83%B3%EF%BD%9C%E3%80%90%E5%85%AC%E5%BC%8F%E3%80%91"
        "%E3%83%9D%E3%82%B1%E3%83%A2%E3%83%B3%E3%82%BB%E3%83%B3%E3%82%BF%E3%83%BC%E3%82%AA"
        "%E3%83%B3%E3%83%A9%E3%82%A4%E3%83%B33.htm"
    ),
    2: (
        _TESTPAGES_BASE
        + "%E3%83%AD%E3%82%B0%E3%82%A4%E3%83%B3%EF%BD%9C%E3%80%90%E5%85%AC%E5%BC%8F%E3%80%91"
        "%E3%83%9D%E3%82%B1%E3%83%A2%E3%83%B3%E3%82%BB%E3%83%B3%E3%82%BF%E3%83%BC%E3%82%AA"
        "%E3%83%B3%E3%83%A9%E3%82%A4%E3%83%B32.htm"
    ),
    3: (
        _TESTPAGES_BASE
        + "%E3%83%AD%E3%82%B0%E3%82%A4%E3%83%B3%EF%BD%9C%E3%80%90%E5%85%AC%E5%BC%8F%E3%80%91"
        "%E3%83%9D%E3%82%B1%E3%83%A2%E3%83%B3%E3%82%BB%E3%83%B3%E3%82%BF%E3%83%BC%E3%82%AA"
        "%E3%83%B3%E3%83%A9%E3%82%A4%E3%83%B3.html"
    ),
}[LOGIN_ERROR_TEST_NUM]

# ──────────────────────────── 预约目标 ────────────────────────────────────────
# 在抽选应募一览页要操作的商品标题，与页面卡片中 .lBox > p 的文字精确匹配
LOTTERY_TARGET_TITLE = "【抽選販売】ポケモン赤・緑 GAME MUSIC COLLECTION with GAME BOY型さいせいマシン"

# ═════════════════ 生产前必须确认的开关（当前为调试值！）═════════════════
# 参数名                    调试值      生产值     说明
# -----------------------------------------------------------------------
# DO_CLICK_LOGIN            False  →   True      False 时填完账密不点击登录
# REQUIRE_OTP               False  →   视需求     False 时跳过验证码流程
# SIMULATE_IP_BAN_FROM_ACCOUNT 3  →   0          > 0 时强制从第N个账号起触发封IP模拟
# SIMULATE_LOGIN_ERROR_PAGE False  →   False      一般不需要改
# ═══════════════════════════════════════════════════════════════════════

# ──────────────────────────── 数据路径 ────────────────────────────────────────
ACCOUNTS_CSV_PATH = "data/accounts.csv"   # 账号列表
BROWSERS_CSV_PATH = "data/browsers.csv"   # 指纹浏览器列表
EMAILS_CSV_PATH   = "data/emails.csv"     # IDLE 监听到的验证码邮件

# ──────────────────────────── 日志 ────────────────────────────────────────────
LOG_DIR = "logs"
# 根 logger 的总闸门等级，控制哪些日志能进入各 Handler
#   DEBUG   → 文件记录 DEBUG+，控制台输出 INFO+（开发调试用，最宽松）
#   INFO    → 文件和控制台均只记录 INFO+（上线正式运行时推荐）
#   WARNING → 只记录警告及以上
LOG_LEVEL = "DEBUG"
