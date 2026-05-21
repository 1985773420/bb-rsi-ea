#!/usr/bin/env python3
"""通过代理从OKX拉取180天15m数据"""
import requests, json, time, sys
from datetime import datetime, timedelta

URL = "https://www.okx.com/api/v5/market/candles"
PROXY = "http://127.0.0.1:2080"
DAYS = 180
TARGET = DAYS * 96

after = int((time.time() - DAYS * 86400) * 1000)
all_bars = []
page = 0

print(f"拉取OKX {DAYS}天 15m数据 (目标{TARGET}根)...")
while len(all_bars) < TARGET and page < 100:
    try:
        r = requests.get(URL, params={"instId":"BTC-USDT-SWAP","bar":"15m","limit":300,"after":str(after)},
                         proxies={"http":PROXY,"https":PROXY}, timeout=30)
        data = r.json().get("data", [])
        if not data: break
        
        for row in data:
            all_bars.append({
                "ts": int(row[0]),
                "o": float(row[1]), "h": float(row[2]),
                "l": float(row[3]), "c": float(row[4]),
            })
        
        after = int(data[0][0]) + 1
        page += 1
        if page % 5 == 0 or len(all_bars) >= TARGET:
            dt = datetime.fromtimestamp(all_bars[-1]["ts"]/1000)
            print(f"  第{page}页 {len(all_bars)}根, 最早{dt.strftime('%Y-%m-%d %H:%M')}")
    except Exception as e:
        print(f"  第{page}页失败: {e}")
        time.sleep(2)
        continue

all_bars.sort(key=lambda x: x["ts"])
print(f"\n✅ {len(all_bars)}根 | {datetime.fromtimestamp(all_bars[0]['ts']/1000).strftime('%Y-%m-%d %H:%M')} ~ {datetime.fromtimestamp(all_bars[-1]['ts']/1000).strftime('%Y-%m-%d %H:%M')}")

with open("/tmp/okx_180d.json", "w") as f:
    json.dump(all_bars, f)
print("保存到 /tmp/okx_180d.json")
