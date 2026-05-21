#!/usr/bin/env python3
"""迁移历史JSON数据到SQLite"""
import json, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from datastore import insert_candles, count, get_stats, get_last_update_time

print("读取 JSON 数据...", flush=True)
with open("/tmp/btc_15m_all_okx.json", "r") as f:
    raw = json.load(f)

print(f"共 {len(raw)} 原始记录，开始导入...", flush=True)

batch_size = 5000
total_inserted = 0
for i in range(0, len(raw), batch_size):
    batch = raw[i:i+batch_size]
    inserted = insert_candles(batch)
    total_inserted += inserted
    if i % 50000 == 0:
        print(f"  进度: {i}/{len(raw)}", flush=True)

print(f"\n✅ 迁移完成！新增 {total_inserted} 条", flush=True)
print(f"数据库中总计: {count()} 条", flush=True)
stats = get_stats()
if stats:
    from datetime import datetime
    print(f"时间范围: {datetime.fromtimestamp(stats['from_ts']/1000)} → {datetime.fromtimestamp(stats['to_ts']/1000)}")
    print(f"价格范围: {stats['min_price']} ~ {stats['max_price']}")
print(f"最后更新: {get_last_update_time()}")
