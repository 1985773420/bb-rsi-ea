#!/usr/bin/env python3
"""
BTC 5分钟 快速均线回测 — 数据受限就用现有300根验证策略
MA730(2年日线)定方向 + MA200(日线)过滤 + MA5/MA13快线入场
"""
import json, subprocess, sys, math
from datetime import datetime, timezone, timedelta

def okx_cmd(args):
    cmd = ["okx"] + args
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0: raise RuntimeError(f"okx error: {r.stderr.strip()}")
    return json.loads(r.stdout)

def parse_bar(bar):
    return {"ts": int(bar[0]), "o": float(bar[1]), "h": float(bar[2]),
            "l": float(bar[3]), "c": float(bar[4]),
            "v": float(bar[5]) if len(bar) > 5 else 0,
            "dt": datetime.fromtimestamp(int(bar[0])/1000, tz=timezone.utc)}

# ===== 拉数据 =====
print("拉取日线 + 5分钟K线...")
daily_raw = okx_cmd(["market", "candles", "BTC-USDT", "--bar", "1D", "--limit", "300", "--json"])
daily = [parse_bar(b) for b in daily_raw]; daily.sort(key=lambda x: x["ts"])
print(f"  日线: {len(daily)}条, {daily[0]['dt'].date()}~{daily[-1]['dt'].date()}")

m5_raw = okx_cmd(["market", "candles", "BTC-USDT", "--bar", "5m", "--limit", "300", "--json"])
m5 = [parse_bar(b) for b in m5_raw]; m5.sort(key=lambda x: x["ts"])
print(f"  5m: {len(m5)}条, {m5[0]['dt']}~{m5[-1]['dt']}")

n_daily = len(daily)
dc = [b["c"] for b in daily]
ma730 = sum(dc[-min(730,n_daily):]) / min(730,n_daily)
ma200 = sum(dc[-min(200,n_daily):]) / min(200,n_daily)
print(f"  MA{min(730,n_daily)}(2年): {ma730:.2f} | MA200: {ma200:.2f}")
print(f"  BTC当前: {m5[-1]['c']:.2f} | 趋势: {'多头' if m5[-1]['c']>ma730 else '空头'}")

# 日线MA匹配到5分钟
def daily_ma_at(daily_data, period, target_ts):
    td = datetime.fromtimestamp(target_ts/1000, tz=timezone.utc).date()
    cl = []
    for b in reversed(daily_data):
        if datetime.fromtimestamp(b["ts"]/1000, tz=timezone.utc).date() <= td:
            cl.append(b["c"])
    cl.reverse()
    return sum(cl[-period:]) / period if len(cl) >= period else None

m5c = [b["c"] for b in m5]

# MA5 和 MA13 (5分钟快速均线)
ma5_vals, ma13_vals = [], []
ma5_p, ma13_p = [], []
for i in range(len(m5c)):
    if i >= 4:
        ma5_vals.append(sum(m5c[i-4:i+1])/5)
        ma5_p.append(sum(m5c[i-5:i])/5 if i>=5 else None)
    else:
        ma5_vals.append(None); ma5_p.append(None)
    if i >= 12:
        ma13_vals.append(sum(m5c[i-12:i+1])/13)
        ma13_p.append(sum(m5c[i-13:i])/13 if i>=13 else None)
    else:
        ma13_vals.append(None); ma13_p.append(None)

ma730_arr = [daily_ma_at(daily, min(730,n_daily), b["ts"]) for b in m5]
ma200_arr = [daily_ma_at(daily, min(200,n_daily), b["ts"]) for b in m5]

# ===== 多组参数回测 =====
param_sets = [
    # (TP%, SL%, MAX_BARS, MA_fast, MA_slow, name)
    # 方案A: 极紧，高频
    {"tp": 0.0010, "sl": 0.0008, "max_bars": 8, "name": "A-极紧(0.10/0.08%, 40min)"},
    # 方案B: 宽松一点
    {"tp": 0.0015, "sl": 0.0010, "max_bars": 10, "name": "B-适中(0.15/0.10%, 50min)"},
    # 方案C: 更宽
    {"tp": 0.0025, "sl": 0.0015, "max_bars": 12, "name": "C-较宽(0.25/0.15%, 60min)"},
]

for ps in param_sets:
    TP = ps["tp"]; SL = ps["sl"]; MAX_BARS = ps["max_bars"]
    
    trades = []
    position = None
    
    for gi, bar in enumerate(m5):
        c = bar["c"]
        ma7v = ma730_arr[gi]; ma200v = ma200_arr[gi]
        ma5v = ma5_vals[gi]; ma13v = ma13_vals[gi]
        ma5pv = ma5_p[gi]; ma13pv = ma13_p[gi]
        
        if None in (ma7v, ma200v, ma5v, ma13v, ma5pv, ma13pv):
            continue
        
        trend_up = c > ma7v; trend_down = c < ma7v
        near_ma = abs(c - ma7v) / ma7v < 0.005
        strong_up = c > ma200v; strong_down = c < ma200v
        golden = ma5pv <= ma13pv and ma5v > ma13v
        death = ma5pv >= ma13pv and ma5v < ma13v
        
        if position is not None:
            ep = position["price"]; ei = position["idx"]; held = gi - ei
            pnl = (c-ep)/ep*100 if position["type"]=="long" else (ep-c)/ep*100
            
            reason = None
            if pnl >= TP*100: reason = "止盈"
            elif pnl <= -SL*100: reason = "止损"
            elif position["type"]=="long" and (trend_down or death): reason = "反"
            elif position["type"]=="short" and (trend_up or golden): reason = "反"
            elif held >= MAX_BARS: reason = "超时"
            
            if reason:
                trades.append({"dir": position["type"], "in": m5[ei]["dt"].strftime("%m-%d %H:%M"),
                              "out": bar["dt"].strftime("%m-%d %H:%M"),
                              "entry": ep, "exit": c, "pnl": round(pnl,4),
                              "bars": held, "mins": held*5, "reason": reason})
                position = None
            continue
        
        if near_ma: continue
        
        if trend_up and strong_up and golden:
            position = {"type": "long", "idx": gi, "price": c}
        elif trend_down and strong_down and death:
            position = {"type": "short", "idx": gi, "price": c}
    
    # 强制平仓
    if position:
        lb = m5[-1]; c = lb["c"]; ep = position["price"]
        pnl = (c-ep)/ep*100 if position["type"]=="long" else (ep-c)/ep*100
        held = len(m5)-1-position["idx"]
        trades.append({"dir": position["type"], "in": m5[position["idx"]]["dt"].strftime("%m-%d %H:%M"),
                      "out": lb["dt"].strftime("%m-%d %H:%M"),
                      "entry": ep, "exit": c, "pnl": round(pnl,4),
                      "bars": held, "mins": held*5, "reason": "结束"})
    
    # 输出
    wins = sum(1 for t in trades if t["pnl"]>0)
    total = sum(t["pnl"] for t in trades)
    avg = total/len(trades) if trades else 0
    
    print(f"\n{'─'*85}")
    print(f"📋 {ps['name']} | 交易{len(trades)}笔 | 胜率{wins}/{len(trades)}={wins/len(trades)*100:.1f}% | 盈亏{total:+.2f}% | 均{avg:+.4f}%")
    
    if trades:
        for t in trades:
            d = "多" if t["dir"]=="long" else "空"
            p = f"+{t['pnl']:.2f}%" if t["pnl"]>=0 else f"{t['pnl']:.2f}%"
            print(f"  {d} {t['in']}→{t['out']} {t['entry']:.1f}→{t['exit']:.1f} {p:>8} {t['mins']:>3}min {t['reason']}")
    
    # 夏普
    if len(trades)>1:
        pnls=[t["pnl"] for t in trades]
        a=sum(pnls)/len(pnls); s=math.sqrt(sum((x-a)**2 for x in pnls)/len(pnls))
        sharpe=a/s*math.sqrt(len(trades)) if s>0 else 0
        print(f"  夏普: {sharpe:.2f}")
        if wins and len(trades)-wins:
            aw=sum(t["pnl"] for t in trades if t["pnl"]>0)/wins
            al=abs(sum(t["pnl"] for t in trades if t["pnl"]<=0)/(len(trades)-wins))
            print(f"  盈亏比: {aw:.3f}% / {al:.3f}% = {aw/al:.2f}")

print(f"\n{'='*85}")
print("⚠️ 数据仅25小时(300根5min)，非7天完整回测。OKX API限制5分钟K线最多300根。")
print(f"{'='*85}")
