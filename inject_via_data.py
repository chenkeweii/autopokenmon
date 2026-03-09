"""
inject_via_data.py — 将 Via 浏览器的宝可梦中心数据注入到 Chrome

使用步骤：
  1. 手机 Via 浏览器打开 https://www.pokemoncenter-online.com（保持登录状态最佳）
  2. 在 Via 地址栏输入下面的书签脚本（一行 javascript: 开头的代码），执行后复制弹出的 JSON
  3. 将复制的内容保存为本目录下的 via_data.json 文件
  4. adb forward tcp:9222 localabstract:chrome_devtools_remote
  5. python inject_via_data.py

书签脚本（在 Via 地址栏粘贴并访问）：
────────────────────────────────────────────────────────────
javascript:(function(){var d={cookies:document.cookie,ls:{}};for(var i=0;i<localStorage.length;i++){var k=localStorage.key(i);d.ls[k]=localStorage.getItem(k);}var j=JSON.stringify(d,null,2);if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(j).then(function(){alert('✅ 已复制！localStorage:'+Object.keys(d.ls).length+'条 cookie:'+document.cookie.split(';').filter(Boolean).length+'条 请粘贴保存为 via_data.json');});}else{var a=document.createElement('a');a.href='data:text/json;charset=utf-8,'+encodeURIComponent(j);a.download='via_data.json';a.click();}})();
────────────────────────────────────────────────────────────

注意：httpOnly 的 cookie 无法被 JS 读取，但 Gigya 设备令牌在 localStorage 里，
      这是最关键的数据，可以正常导出。
"""

import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

CDP_ENDPOINT = "http://127.0.0.1:9222"
DATA_FILE    = "via_data.json"
TARGET_ORIGIN = "https://www.pokemoncenter-online.com"


async def inject(data: dict) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(CDP_ENDPOINT)
        ctx  = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        # 必须先导航到同 origin，否则 localStorage.setItem 会跨域报错
        if TARGET_ORIGIN not in page.url:
            print(f"  → 导航到 {TARGET_ORIGIN} ...")
            await page.goto(TARGET_ORIGIN, wait_until="domcontentloaded", timeout=20000)

        # ── 注入 localStorage ──────────────────────────────────────────────
        ls = data.get("ls", {})
        if ls:
            # 过滤掉明显无关的键（第三方脚本写入的噪音），只保留 gigya / pokemon 相关
            relevant = {k: v for k, v in ls.items()
                        if any(kw in k.lower() for kw in
                               ("gigya", "gig_", "pokemon", "pco_", "uid", "session", "device"))}
            all_keys = ls  # 也保留全量作为备用

            js_set = ";".join(
                f"localStorage.setItem({json.dumps(k)},{json.dumps(v)})"
                for k, v in ls.items()
            )
            await page.evaluate(f"() => {{ {js_set} }}")
            print(f"  ✅ localStorage 注入完成：{len(ls)} 条（Gigya 相关 {len(relevant)} 条）")
            for k in sorted(relevant.keys()):
                val_preview = str(relevant[k])[:60]
                print(f"     {k[:50]} = {val_preview}")
        else:
            print("  ⚠ via_data.json 中 localStorage 为空")

        # ── 注入 cookie ─────────────────────────────────────────────────────
        raw_cookies = data.get("cookies", "").strip()
        if raw_cookies:
            cookies_to_add = []
            for part in raw_cookies.split(";"):
                part = part.strip()
                if not part or "=" not in part:
                    continue
                name, _, value = part.partition("=")
                cookies_to_add.append({
                    "name":     name.strip(),
                    "value":    value.strip(),
                    "domain":   ".pokemoncenter-online.com",
                    "path":     "/",
                    "secure":   True,
                    "sameSite": "Lax",
                })
            if cookies_to_add:
                await ctx.add_cookies(cookies_to_add)
                print(f"  ✅ Cookie 注入完成：{len(cookies_to_add)} 条")
        else:
            print("  ⚠ via_data.json 中 cookie 为空（Via 可能未登录或页面未完全加载）")

        # ── 刷新让 Gigya SDK 重新读取 localStorage ────────────────────────
        print("  → 刷新页面，让 Gigya 重新识别设备...")
        await page.reload(wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(3)

        # ── 验证：读取注入后的关键 Gigya 键 ──────────────────────────────
        gigya_keys = await page.evaluate("""() => {
            var result = {};
            for (var i = 0; i < localStorage.length; i++) {
                var k = localStorage.key(i);
                if (k && (k.includes('gigya') || k.includes('gig_'))) {
                    result[k] = localStorage.getItem(k);
                }
            }
            return result;
        }""")
        if gigya_keys:
            print(f"  ✅ 验证通过：Chrome localStorage 中现有 {len(gigya_keys)} 条 Gigya 数据")
        else:
            print("  ⚠ 验证：未找到 Gigya 相关 localStorage（Via 可能从未登录宝可梦中心）")

        await browser.close()
        print()
        print("注入完成！建议再手动在 Chrome 里登录一次宝可梦中心，让 Gigya 刷新设备令牌后再跑 main.py")


def main() -> None:
    data_path = Path(DATA_FILE)
    if not data_path.exists():
        print(f"错误：找不到 {DATA_FILE}")
        print()
        print("请先在 Via 浏览器的宝可梦中心页面执行书签脚本，将数据复制后保存为 via_data.json")
        print("书签脚本内容见本文件顶部注释。")
        sys.exit(1)

    print(f"读取 {DATA_FILE} ...")
    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"JSON 解析失败：{e}")
        print("请确认 via_data.json 内容完整（从 { 开始到 } 结束）")
        sys.exit(1)

    ls_count = len(data.get("ls", {}))
    ck_count = len([c for c in data.get("cookies", "").split(";") if c.strip()])
    print(f"数据概览：localStorage {ls_count} 条，cookie {ck_count} 条")

    asyncio.run(inject(data))


if __name__ == "__main__":
    main()
