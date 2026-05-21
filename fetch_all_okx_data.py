#!/usr/bin/env python3
"""拉取 OKX BTC-USDT 15m 所有历史数据并保存"""
import requests, time, json
from datetime import datetime, timezone

URL = "https://www.okx.com/api/v5/market/history-candles"
PROXY = {"http": "http://127.0.0.1:2080", "https": "http://127.0.0.1:2080"}
SAVE_PATH = "/tmp/btc_15m_all_okx.json"

def main():
    target_end = int(time.time() * 1000)
    all_bars = []
    limit = 300
    iterations = 0

    print(f"正在拉取 OKX BTC-USDT 15m 所有可用历史数据...", flush=True)
    print(f"数据将保存到: {SAVE_PATH}", flush=True)

    while True:
        try:
            params = {
                "instId": "BTC-USDT",
                "bar": "15m",
                "limit": limit,
                "after": str(target_end)
            }
            res = requests.get(URL, params=params, proxies=PROXY, timeout=30)
            data = res.json().get("data", [])

            if not data or len(data) == 0:
                print("\n✅ 已拉取完所有可用数据！", flush=True)
                break

            all_bars.extend(data)
            target_end = int(data[-1][0])
            iterations += 1
            time.sleep(0.1)

            if iterations % 20 == 0:
                dt = datetime.fromtimestamp(int(data[-1][0]) / 1000, tz=timezone.utc)
                print(f"  已获取 {len(all_bars)} 根，最早 {dt.strftime('%Y-%m-%d %H:%M')}", flush=True)

        except Exception as e:
            print(f"\n❌ 拉取错误: {e}", flush=True)
            time.sleep(2)
            continue

    # 保存
    print(f"\n正在保存 {len(all_bars)} 根数据到 {SAVE_PATH}...", flush=True)
    with open(SAVE_PATH, "w") as f:
        json.dump(all_bars, f)
    print("✅ 保存完成！", flush=True)

if __name__ == "__main__":
    main()
