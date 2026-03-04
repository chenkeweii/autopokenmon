from __future__ import annotations
import os
import sys

# 确保脚本所在目录在 sys.path 最前（嵌入式 Python 不自动添加）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(
    sys.executable if getattr(sys, "frozen", False) else __file__
))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
os.chdir(_SCRIPT_DIR)

# Python 3.8+ DLL 搜索路径变更：需显式注册嵌入式 Python 目录
if hasattr(os, 'add_dll_directory'):
    _python_dir = os.path.join(_SCRIPT_DIR, 'python')
    if os.path.isdir(_python_dir):
        os.add_dll_directory(_python_dir)

""" —— 批量创建 Nstbrowser 指纹环境并绑定唯一 socks5 代理

使用方法：
    1. 在 config.py 中填写 PROXY_* 和 PROFILE_* 参数
    2. 确保 Nstbrowser 客户端正在运行
    3. python setup_profiles.py          # 正常运行
       python setup_profiles.py --dry-run # 仅预览，不实际创建

创建规则：
    - 有多少个端口 (PROXY_PORT_START ~ PROXY_PORT_END) 就创建多少个 Profile
    - 每个 Profile 绑定一个唯一的代理端口，互不重复
    - 命名格式：{PROFILE_NAME_PREFIX}_{起始序号}, {起始序号+1}, ...
      起始序号自动基于现有 Profile 数量累加，避免命名冲突
"""

import random
import time

import requests

import config

# ─────────────────────────────────────────────────────────────────────────────
BASE_URL = f"http://{config.NST_HOST}/api/v2"
HEADERS  = {"x-api-key": config.NST_API_KEY, "Content-Type": "application/json"}

# 尽量像真机的指纹配置
#   BasedOnIp → 语言/时区/地理位置自动跟随代理 IP，确保指纹与代理地区一致
#   Noise     → Canvas/WebGL/Audio 加噪，防止跨账号关联，而非直接屏蔽（屏蔽反而更显眼）
#   Masked    → WebRTC/字体/语音 隐藏，避免泄露本机信息
#   Real/Allow → 电池/GPU 保持真实，屏蔽这些在正常用户中极为罕见
_FINGERPRINT_FLAGS = {
    "audio":             "Noise",
    "battery":           "Real",
    "canvas":            "Noise",
    "clientRect":        "Noise",
    "fonts":             "Masked",
    "geolocation":       "BasedOnIp",
    "geolocationPopup":  "Prompt",
    "gpu":               "Allow",
    "localization":      "BasedOnIp",   # 自动根据代理 IP 设置语言和时区
    "screen":            "Real",
    "speech":            "Masked",
    "timezone":          "BasedOnIp",
    "webgl":             "Noise",
    "webrtc":            "Masked",      # 隐藏本机 LAN IP，避免 WebRTC 泄露
}

# 硬件参数随机池：使每个 Profile 的设备信息略有差异，模拟真实设备多样性
_DEVICE_MEMORY_POOL        = [4, 8, 8]          # 8GB 更常见，适当加权
_HARDWARE_CONCURRENCY_POOL = [4, 8, 8, 12, 16]  # 8/12 核最普遍


# ─────────────────────────── 工具函数 ────────────────────────────────────────

def _build_proxy_url(port: int) -> str:
    """拼装单条代理 URL。"""
    proto = config.PROXY_PROTOCOL.rstrip("://")
    user  = config.PROXY_USERNAME
    pwd   = config.PROXY_PASSWORD
    host  = config.PROXY_HOST

    if user and pwd:
        return f"{proto}://{user}:{pwd}@{host}:{port}"
    return f"{proto}://{host}:{port}"


def _count_existing_profiles() -> int:
    """获取当前账号下的 Profile 总数，用于计算命名起始序号。"""
    url = f"{BASE_URL}/profiles/cursor"
    try:
        resp = requests.get(url, headers=HEADERS, params={"pageSize": 1}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        # API 返回的 totalDocs 字段（某些版本不一定有，fallback 为 0）
        total = data.get("data", {}).get("totalDocs", 0)
        return int(total)
    except Exception:
        return 0


def _create_profile(name: str, proxy_url: str) -> dict | None:
    """
    调用 POST /api/v2/profiles 创建一个 Profile。

    Returns
    -------
    dict or None
        成功返回 API 响应中的 data 字段（含 profileId），失败返回 None。
    """
    payload = {
        "name":            name,
        "platform":        "Windows",
        "kernelMilestone": "132",          # Chrome 132，当前最广泛的稳定版
        "groupName":       config.PROFILE_GROUP_NAME,
        "proxy":           proxy_url,
        "fingerprint": {
            "flags":               _FINGERPRINT_FLAGS,
            "deviceMemory":        random.choice(_DEVICE_MEMORY_POOL),
            "hardwareConcurrency": random.choice(_HARDWARE_CONCURRENCY_POOL),
            "restoreLastSession":  True,    # 打开时恢复上次会话，符合真实用户习惯
            "doNotTrack":          False,   # 默认关闭，开启反而更异常
        },
    }

    try:
        resp = requests.post(f"{BASE_URL}/profiles", headers=HEADERS, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        print(f"  [ERROR] HTTP 请求失败: {exc}")
        return None

    if data.get("code") not in (0, 200):
        print(f"  [ERROR] API 返回错误: code={data.get('code')}, msg={data.get('msg')}")
        return None

    return data.get("data")


# ─────────────────────────────── 主逻辑 ──────────────────────────────────────

def main(dry_run: bool = False) -> None:
    port_list = list(range(config.PROXY_PORT_START, config.PROXY_PORT_END + 1))
    total     = len(port_list)

    print("=" * 60)
    print("Nstbrowser 批量创建指纹环境")
    print("=" * 60)
    print(f"  代理协议 : {config.PROXY_PROTOCOL}")
    print(f"  代理地址 : {config.PROXY_HOST}")
    print(f"  端口范围 : {config.PROXY_PORT_START} ~ {config.PROXY_PORT_END}")
    print(f"  代理数量 : {total} 个")
    print(f"  命名前缀 : {config.PROFILE_NAME_PREFIX}")
    print(f"  目标分组 : {config.PROFILE_GROUP_NAME}")
    print(f"  运行模式 : {'🔍 预览（--dry-run）' if dry_run else '🚀 实际创建'}")
    print()

    if not dry_run:
        answer = input(f"确认创建 {total} 个 Profile？(y/N) ").strip().lower()
        if answer != "y":
            print("已取消。")
            return
        print()

    # 计算命名起始序号：避免与已有 Profile 命名冲突
    existing_count = _count_existing_profiles()
    start_index    = existing_count + 1
    print(f"当前已有 {existing_count} 个 Profile，本次从 {config.PROFILE_NAME_PREFIX}_{start_index} 开始命名。\n")

    success_list: list[dict] = []
    fail_list:    list[int]  = []

    for i, port in enumerate(port_list):
        idx       = start_index + i
        name      = f"{config.PROFILE_NAME_PREFIX}_{idx}"
        proxy_url = _build_proxy_url(port)

        print(f"[{i+1:>3}/{total}] {name:<15} 代理: {proxy_url}", end="  ")

        if dry_run:
            print("(跳过，dry-run 模式)")
            success_list.append({"name": name, "proxy": proxy_url, "profileId": "N/A"})
            continue

        result = _create_profile(name, proxy_url)
        if result:
            profile_id = result.get("profileId", "?")
            print(f"✓ profileId={profile_id}")
            success_list.append({"name": name, "proxy": proxy_url, "profileId": profile_id})
        else:
            print("✗ 创建失败")
            fail_list.append(port)

        # 避免 API 速率限制
        if i < total - 1:
            time.sleep(0.3)

    # ── 汇总 ──────────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print(f"完成！成功 {len(success_list)} 个，失败 {len(fail_list)} 个")

    if fail_list:
        print(f"\n失败端口列表（可手动重试）：{fail_list}")

    if not dry_run and success_list:
        print("\n提示：运行 python main.py 时会自动从 Nstbrowser API 同步新 Profile 到 browsers.csv")


if __name__ == "__main__":
    is_dry_run = "--dry-run" in sys.argv
    main(dry_run=is_dry_run)
