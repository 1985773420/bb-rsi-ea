#!/usr/bin/env python3
"""BB+RSI v2 TP/SL参数对比回测 (去MA730+RSI65/35+近3K线扫描)"""
import requests, math, json
from datetime import datetime, timezone

GATE_URL = "https://api.gateio.ws/api/v4/spot/candlesticks"
PROXY = "http://127.0.0.1:2080"

BB_PERIOD = 20; BB_STD = 2; RSI_PERIOD = 10
RSI_HIGH = 65; RSI_LOW = 35; ATR_VOL_FILTER = 0.8
MAX_BARS = 24; FEE_PCT = 0.0007

VARIANTS = [
    {"name": "当前(TP0.8/SL0.4)", "tp": 0.008, "sl": 0.004},
    {"name": "TP0.6/SL0.3", "tp": 0.006, "sl": 0.003},
    {"name": "TP0.5/SL0.3", "tp": 0.005, "sl": 0.003},
    {"name": "TP0.7/SL0.35", "tp": 0.007, "sl": 0.0035},
]

def fetch_all(target=3000):
    bars = []
    for _ in range(5):
        to_ts = bars[0]["ts"] if bars else None
        params = {"currency_pair": "BTC_USDT", "interval": "15m", "limit": 1000}
        if to_ts: params["to"] = to_ts
        try:
            r = requests.get(GATE_URL, params=params, proxies={"http": PROXY, "https": PROXY}, timeout=30)
            data = r.json()
            if not data: break
            chunk = [{"ts": int(row[0]), "o": float(row[5]), "h": float(row[3]),
                      "l": float(row[4]), "c": float(row[2]), "v": float(row[6])} for row in data]
            if bars:
                chunk = [b for b in chunk if b["ts"] < bars[0]["ts"]]
            bars = chunk + bars
            if len(bars) >= target: break
            if len(chunk) < 1000: break
        except: break
    bars.sort(key=lambda x: x["ts"])
    return bars

def calc_indicators(bars):
    closes = [b["c"] for b in bars]; highs = [b["h"] for b in bars]; lows = [b["l"] for b in bars]
    n = len(closes)
    
    bb_u, bb_l = [None]*n, [None]*n
    for i in range(BB_PERIOD-1, n):
        w = closes[i-BB_PERIOD+1:i+1]
        sma = sum(w)/BB_PERIOD
        std = (sum((x-sma)**2 for x in w)/BB_PERIOD)**0.5
        bb_u[i] = sma + BB_STD*std; bb_l[i] = sma - BB_STD*std
    
    rsi = [None]*n
    for i in range(RSI_PERIOD, n):
        gains = sum(max(closes[j]-closes[j-1], 0) for j in range(i-RSI_PERIOD+1, i+1))/RSI_PERIOD
        losses = sum(max(closes[j-1]-closes[j], 0) for j in range(i-RSI_PERIOD+1, i+1))/RSI_PERIOD
        rsi[i] = 100 - 100/(1+gains/losses) if losses > 0 else 100
    
    atr_pct = [None]*n
    for i in range(14, n):
        tr = [max(highs[j]-lows[j], abs(highs[j]-closes[j-1]), abs(lows[j]-closes[j-1])) for j in range(i-13, i+1)]
        atr_pct[i] = (sum(tr)/14) / closes[i] * 100
    valid = [v for v in atr_pct if v is not None]
    atr_mean = sum(valid)/len(valid) if valid else 0.35
    return bb_u, bb_l, rsi, atr_pct, atr_mean

def backtest(bars, tp=0.008, sl=0.004, label=""):
    bb_u, bb_l, rsi, atr_pct, atr_mean = calc_indicators(bars)
    trades = []
    in_pos = None; entry_bar = 0; entry_px = 0
    equity = [1.0]
    min_idx = max(BB_PERIOD, RSI_PERIOD, 14) + 1
    
    for i in range(min_idx, len(bars)):
        bar = bars[i]; c = bar["c"]
        
        if in_pos:
            bars_held = i - entry_bar
            pnl = (c-entry_px)/entry_px if in_pos=="long" else (entry_px-c)/entry_px
            
            if pnl >= tp:
                trades.append({"side": in_pos, "pnl": pnl-FEE_PCT, "bars": bars_held, "reason": "TP"})
                equity.append(equity[-1]*(1+pnl-FEE_PCT))
                in_pos = None; continue
            if pnl <= -sl:
                trades.append({"side": in_pos, "pnl": pnl-FEE_PCT, "bars": bars_held, "reason": "SL"})
                equity.append(equity[-1]*(1+pnl-FEE_PCT))
                in_pos = None; continue
            if bars_held >= MAX_BARS:
                trades.append({"side": in_pos, "pnl": pnl-FEE_PCT, "bars": bars_held, "reason": "TO"})
                equity.append(equity[-1]*(1+pnl-FEE_PCT))
                in_pos = None; continue
            continue
        
        signal = None
        for j in range(i-1, max(i-1-3, min_idx-1), -1):
            if bb_u[j] is None or rsi[j] is None or atr_pct[j] is None: continue
            if atr_pct[j] < atr_mean * ATR_VOL_FILTER: continue
            cj = bars[j]["c"]
            if cj > bb_u[j] and rsi[j] > RSI_HIGH:
                signal = "short"; entry_px = cj; break
            elif cj < bb_l[j] and rsi[j] < RSI_LOW:
                signal = "long"; entry_px = cj; break
        if not signal: continue
        in_pos = signal; entry_bar = i
    
    if in_pos:
        c = bars[-1]["c"]
        pnl = (c-entry_px)/entry_px if in_pos=="long" else (entry_px-c)/entry_px
        trades.append({"side": in_pos, "pnl": pnl-FEE_PCT, "bars": len(bars)-1-entry_bar, "reason": "OPEN"})
    return trades, equity

def stats(trades):
    if not trades: return {"n":0,"wr":0,"cmp":0,"sl":0,"tp":0,"to":0}
    wins = [t for t in trades if t["pnl"]>0]; loss = [t for t in trades if t["pnl"]<=0]
    eq = 1.0
    for t in trades: eq*=(1+t["pnl"])
    return {"n":len(trades),"wr":len(wins)/len(trades)*100,
            "cmp":(eq-1)*100,"avg":sum(t["pnl"]for t in trades)/len(trades)*100,
            "avg_w":sum(t["pnl"]for t in wins)/len(wins)*100 if wins else 0,
            "avg_l":sum(t["pnl"]for t in loss)/len(loss)*100 if loss else 0,
            "sl":sum(1 for t in trades if t["reason"]=="SL"),
            "tp":sum(1 for t in trades if t["reason"]=="TP"),
            "to":sum(1 for t in trades if t["reason"]=="TO")}

def main():
    print("="*85)
    print("BB+RSI v2 TP/SL参数对比回测")
    print("="*85)
    
    bars = fetch_all(3000)
    if len(bars) < 500:
        print(f"❌ 数据不足: {len(bars)}根"); return
    
    total = len(bars)
    print(f"\n✅ {total}根K线 | {datetime.fromtimestamp(bars[0]['ts']).strftime('%m-%d %H:%M')} ~ {datetime.fromtimestamp(bars[-1]['ts']).strftime('%m-%d %H:%M')}")
    
    periods = {}
    for days in [7, 14, 30]:
        start = max(0, total - days * 96)
        periods[days] = bars[start:]
    
    for v in VARIANTS:
        print(f"\n{'='*85}")
        print(f"  {v['name']}")
        print(f"{'='*85}")
        for days, pb in periods.items():
            trades, equity = backtest(pb, v["tp"], v["sl"])
            s = stats(trades)
            print(f"  {days}天: {s['n']:>3}笔 | 胜率{s['wr']:.1f}% | 复利{s['cmp']:+6.2f}% | "
                  f"TP{s['tp']}/{s['n']} SL{s['sl']}/{s['n']} TO{s['to']}/{s['n']} | "
                  f"均赢{s['avg_w']:+.2f}% 均亏{s['avg_l']:+.2f}%")
    
    # 汇总表
    print(f"\n\n{'='*85}")
    print(f"📊 汇总 (30天)")
    print(f"{'='*85}")
    print(f"{'方案':<25} {'交易':>5} {'胜率':>7} {'复利':>8} {'TP率':>7} {'SL率':>7} {'TO率':>7} {'均赢':>7} {'均亏':>7}")
    print(f"{'-'*85}")
    for v in VARIANTS:
        trades, equity = backtest(periods[30], v["tp"], v["sl"])
        s = stats(trades)
        print(f"{v['name']:<25} {s['n']:>5} {s['wr']:>6.1f}% {s['cmp']:>+7.2f}% "
              f"{s['tp']/s['n']*100:>6.1f}% {s['sl']/s['n']*100:>6.1f}% {s['to']/s['n']*100:>6.1f}% "
              f"{s['avg_w']:>+6.2f}% {s['avg_l']:>+6.2f}%")

if __name__ == "__main__":
    main()
