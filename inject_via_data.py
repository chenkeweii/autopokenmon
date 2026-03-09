"""
inject_via_data.py — 将 Via 浏览器的宝可梦中心数据注入到 Chrome

Via 信任分高的根本原因：
  Gigya 把设备指纹/历史数据存在 localStorage 和 IndexedDB 里。
  用了很久的 Via = Gigya 认识这台设备 = 高信任分 = 不用签合约、抽签页不要求二次登录。
  新 Chrome = Gigya 第一次见 = 最低信任分 = 签合约 + 二次登录 + 风控。

使用步骤：
  1. 手机 Via 浏览器打开 https://www.pokemoncenter-online.com（保持登录状态最佳）
  2. 在 Via 地址栏粘贴下面的书签脚本并访问，等弹出"已复制"提示
  3. 将复制的 JSON 内容保存为本目录下的 via_data.json 文件
  4. adb forward tcp:9222 localabstract:chrome_devtools_remote
  5. python inject_via_data.py
  6. 注入后在手机 Chrome 里手动登录一次宝可梦中心，让 Gigya 服务器认识新设备
  7. 之后跑 main.py 即可

书签脚本（在 Via 地址栏粘贴并访问，导出 localStorage + IndexedDB + cookie）：
────────────────────────────────────────────────────────────
javascript:(function(){var d={cookies:document.cookie,ls:{},idb:{}};for(var i=0;i<localStorage.length;i++){var k=localStorage.key(i);d.ls[k]=localStorage.getItem(k);}function exportIDB(cb){var dbs=['gigya','GigyaDB'];var results={};var pending=dbs.length;if(!pending)return cb(results);dbs.forEach(function(name){var req=indexedDB.open(name);req.onsuccess=function(e){var db=e.target.result;var stores=Array.from(db.objectStoreNames);var storeData={};var sp=stores.length;if(!sp){results[name]=storeData;if(--pending===0)cb(results);return;}stores.forEach(function(s){var tx=db.transaction(s,'readonly');var all=[];tx.objectStore(s).openCursor().onsuccess=function(ev){var cur=ev.target.result;if(cur){all.push({key:cur.key,value:cur.value});cur.continue();}else{storeData[s]=all;if(--sp===0){results[name]=storeData;if(--pending===0)cb(results);}}});});};req.onerror=function(){if(--pending===0)cb(results);};});}exportIDB(function(idb){d.idb=idb;var j=JSON.stringify(d);if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(j).then(function(){alert('✅ 已复制！ls:'+Object.keys(d.ls).length+'条 idb:'+Object.keys(d.idb).length+'个DB cookie:'+document.cookie.split(';').filter(Boolean).length+'条');});}else{var a=document.createElement('a');a.href='data:text/json;charset=utf-8,'+encodeURIComponent(j);a.download='via_data.json';a.click();}});})();
────────────────────────────────────────────────────────────

注意：httpOnly 的 cookie 无法被 JS 读取，但 Gigya 核心数据在 localStorage 和
      IndexedDB 里，这些可以完整导出。
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
            relevant = {k: v for k, v in ls.items()
                        if any(kw in k.lower() for kw in
                               ("gigya", "gig_", "pokemon", "pco_", "uid", "session", "device"))}
            js_set = ";".join(
                f"localStorage.setItem({json.dumps(k)},{json.dumps(v)})"
                for k, v in ls.items()
            )
            await page.evaluate(f"() => {{ {js_set} }}")
            print(f"  ✅ localStorage 注入完成：{len(ls)} 条（Gigya 相关 {len(relevant)} 条）")
            for k in sorted(relevant.keys()):
                print(f"     {k[:50]} = {str(relevant[k])[:60]}")
        else:
            print("  ⚠ via_data.json 中 localStorage 为空")

        # ── 注入 IndexedDB（Gigya 最核心的设备指纹存储）────────────────────
        idb_data = data.get("idb", {})
        if idb_data:
            total_records = 0
            for db_name, stores in idb_data.items():
                for store_name, records in stores.items():
                    if not records:
                        continue
                    records_json = json.dumps(records)
                    try:
                        wrote = await page.evaluate(f"""async () => {{
                            return new Promise((resolve, reject) => {{
                                const req = indexedDB.open({json.dumps(db_name)});
                                req.onupgradeneeded = e => {{
                                    const db = e.target.result;
                                    if (!db.objectStoreNames.contains({json.dumps(store_name)})) {{
                                        db.createObjectStore({json.dumps(store_name)});
                                    }}
                                }};
                                req.onsuccess = e => {{
                                    const db = e.target.result;
                                    if (!db.objectStoreNames.contains({json.dumps(store_name)})) {{
                                        resolve(0);
                                        return;
                                    }}
                                    const records = {records_json};
                                    const tx = db.transaction({json.dumps(store_name)}, 'readwrite');
                                    const store = tx.objectStore({json.dumps(store_name)});
                                    let count = 0;
                                    records.forEach(r => {{ store.put(r.value, r.key); count++; }});
                                    tx.oncomplete = () => resolve(count);
                                    tx.onerror = e => reject(e.target.error);
                                }};
                                req.onerror = e => reject(e.target.error);
                            }});
                        }}""")
                        total_records += wrote
                        print(f"  ✅ IndexedDB [{db_name}][{store_name}] 写入 {wrote} 条")
                    except Exception as e:
                        print(f"  ⚠ IndexedDB [{db_name}][{store_name}] 写入失败: {str(e)[:60]}")
            if total_records == 0:
                print("  ⚠ IndexedDB 数据为空（Via 可能未访问过宝可梦中心，或浏览器版本不支持）")
        else:
            print("  ⚠ via_data.json 中无 IndexedDB 数据（请使用新版书签脚本重新导出）")

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

        # ── 刷新让 Gigya SDK 重新读取注入的数据 ──────────────────────────
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
        print("注入完成！下一步：在手机 Chrome 里手动登录一次宝可梦中心")
        print("让 Gigya 服务器把这个设备令牌标记为已验证，之后跑 main.py 信任分就和 Via 一样高了")


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
        print("请确认 via_data.json 内容完整（从 {{ 开始到 }} 结束）")
        sys.exit(1)

    ls_count  = len(data.get("ls", {}))
    ck_count  = len([c for c in data.get("cookies", "").split(";") if c.strip()])
    idb_dbs   = len(data.get("idb", {}))
    print(f"数据概览：localStorage {ls_count} 条，IndexedDB {idb_dbs} 个数据库，cookie {ck_count} 条")

    asyncio.run(inject(data))


if __name__ == "__main__":
    main()
