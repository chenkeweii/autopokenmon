"""
warmup_browser.py — 手机 Chrome 浏览历史预热

在正式跑预约脚本前，通过 CDP 自动访问一批日本常用网站，
积累浏览历史、Cookie、localStorage，提升宝可梦中心的风控信任分。

使用方法：
  1. 手机开启 Chrome + VPN（IIJ 节点）
  2. adb forward tcp:9222 localabstract:chrome_devtools_remote
  3. python warmup_browser.py
  4. 等待结束（约 5~15 分钟）后再跑 main.py
"""

import asyncio
import random
from playwright.async_api import async_playwright

CDP_ENDPOINT = "http://127.0.0.1:9222"

# 预热站点列表：日本主流网站 + 宝可梦关联站点
# 每条格式：(url, 停留秒数最小值, 停留秒数最大值, 描述)
WARMUP_SITES = [
    # 搜索引擎 / 门户（建立普通用户画像）
    ("https://www.google.co.jp", 8, 15, "Google JP"),
    ("https://www.yahoo.co.jp", 10, 20, "Yahoo Japan"),
    ("https://www.bing.com/?cc=jp&setlang=ja", 6, 12, "Bing JP"),

    # 新闻 / 资讯（模拟正常日本网民行为）
    ("https://news.yahoo.co.jp", 12, 25, "Yahoo News JP"),
    ("https://www3.nhk.or.jp/news/", 10, 20, "NHK News"),
    ("https://www.asahi.com", 8, 15, "Asahi Shimbun"),

    # 电商（与宝可梦购物行为接近）
    ("https://www.amazon.co.jp", 15, 30, "Amazon JP"),
    ("https://shopping.yahoo.co.jp", 10, 20, "Yahoo Shopping"),
    ("https://www.rakuten.co.jp", 10, 20, "Rakuten"),

    # 游戏 / 动漫（目标用户画像）
    ("https://www.nintendo.co.jp", 15, 30, "Nintendo JP"),
    ("https://www.pokemon.co.jp", 20, 40, "Pokemon.co.jp（官方）"),
    ("https://www.pokemon-card.com", 12, 25, "宝可梦卡牌"),
    ("https://www.bandai.co.jp", 8, 15, "万代"),

    # 社交 / 通用
    ("https://twitter.com", 10, 20, "Twitter/X"),
    ("https://www.youtube.com/?hl=ja&gl=JP", 10, 20, "YouTube JP"),

    # 目标站点本体（多次访问强化信任）
    ("https://www.pokemoncenter-online.com", 20, 45, "宝可梦中心（首次）"),
    ("https://www.pokemoncenter-online.com/category/cardgame/", 15, 35, "宝可梦中心·卡牌分类"),
    ("https://www.pokemoncenter-online.com/category/figure/", 12, 28, "宝可梦中心·手办分类"),
    ("https://www.pokemoncenter-online.com", 15, 35, "宝可梦中心（二次访问）"),
]


async def warmup():
    print("=" * 60)
    print("浏览器预热开始")
    print(f"CDP 端点: {CDP_ENDPOINT}")
    print(f"共 {len(WARMUP_SITES)} 个站点")
    print("=" * 60)

    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(CDP_ENDPOINT)
        contexts = browser.contexts
        ctx = contexts[0] if contexts else await browser.new_context()
        pages = ctx.pages
        page = pages[0] if pages else await ctx.new_page()

        for i, (url, min_sec, max_sec, desc) in enumerate(WARMUP_SITES, 1):
            stay = random.uniform(min_sec, max_sec)
            print(f"[{i:02d}/{len(WARMUP_SITES)}] {desc} | 停留 {stay:.0f}s ...")
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)

                # 随机滚动模拟阅读
                scroll_times = random.randint(2, 5)
                for _ in range(scroll_times):
                    await asyncio.sleep(stay / scroll_times)
                    scroll_px = random.randint(200, 800)
                    await page.evaluate(f"window.scrollBy(0, {scroll_px})")

                # 偶尔滚回顶部
                if random.random() < 0.4:
                    await asyncio.sleep(random.uniform(0.5, 1.5))
                    await page.evaluate("window.scrollTo(0, 0)")

            except Exception as e:
                print(f"  ⚠ 访问失败（跳过）: {str(e).split(chr(10))[0][:80]}")

        print()
        print("=" * 60)
        print("预热完成！可以运行 main.py 了")
        print("=" * 60)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(warmup())
