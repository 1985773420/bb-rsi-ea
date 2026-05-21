#!/usr/bin/env python3
"""拉取 OKX BTC-USDT-SWAP 15m 所有可用历史数据并存入SQLite"""
import sqlite3, requests, time, os
from datetime import datetime, timezone

URL = "https://www.okx.com/api/v5/market/history-candles"
PROXY = {"http":"http://127.0.0.1:2080","https":"http://127.0.0.1:2080"}
INST_ID = "BTC-USDT-SWAP"
DB_PATH = "/var/lib/bb_rsi/data.db"

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-8000")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS btc_swap_15m (
            ts INTEGER PRIMARY KEY,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON btc_swap_15m(ts)")
    conn.commit()
    conn.close()
    print(f"[DB] 初始化完成: {DB_PATH}", flush=True)

def fetch_all():
    target_end = int(time.time() * 1000)
    total = 0
    iterations = 0

    print(f"拉取 {INST_ID} 15m 所有历史数据...", flush=True)

    while True:
        try:
            r = requests.get(URL, params={"instId":INST_ID,"bar":"15m","limit":300,"after":str(target_end)},
                           proxies=PROXY, timeout=30)
            data = r.json().get("data",[])
            if not data or len(data) == 0:
                print("拉取完成！", flush=True)
                break

            # 批量写入
            rows = [(int(d[0]), float(d[1]), float(d[2]), float(d[3]), float(d[4])) for d in data]
            conn = sqlite3.connect(DB_PATH)
            conn.execute("BEGIN")
            for ts,o,h,l,c in rows:
                try:
                    conn.execute("INSERT OR IGNORE INTO btc_swap_15m(ts,open,high,low,close) VALUES(?,?,?,?,?)",
                               (ts,o,h,l,c))
                except: pass
            conn.commit()
            conn.close()

            total += len(data)
            target_end = int(data[-1][0])
            iterations += 1
            time.sleep(0.08)

            if iterations % 30 == 0:
                dt = datetime.fromtimestamp(int(data[-1][0])/1000,tz=timezone.utc)
                print(f"  已获取 ~{total} 根，最早 {dt.strftime('%Y-%m-%d')}", flush=True)

        except Exception as e:
            print(f"  拉取错误: {e}", flush=True)
            time.sleep(2)
            continue

    return total

def main():
    init_db()
    total = fetch_all()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("SELECT COUNT(*), MIN(ts), MAX(ts) FROM btc_swap_15m")
    count, min_ts, max_ts = cur.fetchone()
    conn.close()
    print(f"\n✅ 拉取完成！共 {count} 根", flush=True)
    if min_ts:
        print(f"   时间: {datetime.fromtimestamp(min_ts/1000)} → {datetime.fromtimestamp(max_ts/1000)}")
    db_size = os.path.getsize(DB_PATH) / 1024 / 1024
    print(f"   DB: {db_size:.1f} MB", flush=True)

if __name__ == "__main__":
    main()
