#!/usr/bin/env python3
"""BB+RSI v2 (去MA730 + RSI 65/35 + 近3K线扫描) 近3天回测"""
import requests, math, json
from datetime import datetime, timezone

GATE_URL = "https://api.gateio.ws/api/v4/spot/candlesticks"
PROXY = "http://127.0.0.1:2080"

# 策略参数 (方案E)
TP_PCT = 0.005; SL_PCT = 0.003; MAX_BARS = 24; FEE_PCT = 0.0007
BB_PERIOD = 20; BB_STD = 2; RSI_PERIOD = 10
RSI_HIGH = 65; RSI_LOW = 35; ATR_VOL_FILTER = 0.8
SCAN_BARS = 3  # 扫描近3根已完成K线

def fetch_bars(limit=500):
    bars = []
    for _ in range(3):
        to_ts = bars[0]["ts"] if bars else None
        params = {"currency_pair": "BTC_USDT", "interval": "15m", "limit": min(limit-len(bars), 1000)}
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
            if len(bars) >= limit: break
        except Exception as e:
            print(f"[FETCH ERROR] {e}"); break
    bars.sort(key=lambda x: x["ts"])
    return bars

def calc_indicators(bars):
    closes = [b["c"] for b in bars]; highs = [b["h"] for b in bars]; lows = [b["l"] for b in bars]
    n = len(closes)
    
    bb_u, bb_l = [None]*n, [None]*n
    for i in range(n):
        if i >= BB_PERIOD-1:
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

def backtest(bars):
    bb_u, bb_l, rsi, atr_pct, atr_mean = calc_indicators(bars)
    trades = []
    in_pos = None; entry_bar = 0; entry_px = 0
    equity = [1.0]
    
    for i in range(50, len(bars)):
        bar = bars[i]; c = bar["c"]
        
        if in_pos:
            bars_held = i - entry_bar
            pnl = (c-entry_px)/entry_px if in_pos=="long" else (entry_px-c)/entry_px
            
            if pnl >= TP_PCT:
                trades.append({"ts": bar["ts"], "side": in_pos, "entry": entry_px, "exit": c, "pnl": pnl-FEE_PCT, "bars": bars_held, "reason": "TP"})
                equity.append(equity[-1]*(1+pnl-FEE_PCT))
                in_pos = None; continue
            if pnl <= -SL_PCT:
                trades.append({"ts": bar["ts"], "side": in_pos, "entry": entry_px, "exit": c, "pnl": pnl-FEE_PCT, "bars": bars_held, "reason": "SL"})
                equity.append(equity[-1]*(1+pnl-FEE_PCT))
                in_pos = None; continue
            if bars_held >= MAX_BARS:
                trades.append({"ts": bar["ts"], "side": in_pos, "entry": entry_px, "exit": c, "pnl": pnl-FEE_PCT, "bars": bars_held, "reason": "TIMEOUT"})
                equity.append(equity[-1]*(1+pnl-FEE_PCT))
                in_pos = None; continue
            continue
        # 开仓 — 扫描近3根已完成K线 (模拟cron每15分钟触发)
        if atr_pct[i] is None: continue
        
        # 只在"cron触发点"检查 — 每15分钟(每1根K线)检查一次
        # 实际cron可能稍有偏差，这里每根K线都当触发点
        
        # 扫描最近SCAN_BARS根已完成K线
        signal = None
        for j in range(i-1, max(i-1-SCAN_BARS, -1), -1):
            if j < 50: break
            if bb_u[j] is None or rsi[j] is None or atr_pct[j] is None: continue
            if atr_pct[j] < atr_mean * ATR_VOL_FILTER: continue
            
            cj = bars[j]["c"]
            if cj > bb_u[j] and rsi[j] > RSI_HIGH:
                signal = "short"; entry_px = cj; break
            elif cj < bb_l[j] and rsi[j] < RSI_LOW:
                signal = "long"; entry_px = cj; break
        
        if not signal: continue
        
        if signal == "short":
            in_pos = "short"; entry_bar = i
        else:
            in_pos = "long"; entry_bar = i
    
    if in_pos:
        c = bars[-1]["c"]
        pnl = (c-entry_px)/entry_px if in_pos=="long" else (entry_px-c)/entry_px
        trades.append({"ts": bars[-1]["ts"], "side": in_pos, "entry": entry_px, "exit": c, "pnl": pnl-FEE_PCT, "bars": len(bars)-1-entry_bar, "reason": "OPEN"})
        equity.append(equity[-1]*(1+pnl-FEE_PCT))
    
    return trades, equity

def main():
    print("="*70)
    print("BB+RSI v2 (去MA730 + RSI 65/35) 近3天回测")
    print("="*70)
    
    bars = fetch_bars(300)
    if len(bars) < 50:
        print("❌ 数据不足"); return
    
    # 取最近3天 = 96*3 = 288根
    recent = bars[-288:]
    print(f"\n数据: {len(recent)}根K线 | {datetime.fromtimestamp(recent[0]['ts']).strftime('%m-%d %H:%M')} ~ {datetime.fromtimestamp(recent[-1]['ts']).strftime('%m-%d %H:%M')}")
    print(f"最新: BTC {recent[-1]['c']:.0f}")
    
    trades, equity = backtest(recent)
    
    print(f"\n{'='*70}")
    print(f"{'#':>3} {'时间':<17} {'方向':<6} {'入场':>9} {'出场':>9} {'盈亏':>8} {'原因':<10} {'持仓':>6}")
    print(f"{'-'*70}")
    
    for i, t in enumerate(trades, 1):
        ts = datetime.fromtimestamp(t["ts"]).strftime("%m-%d %H:%M")
        arrow = "↑多" if t["side"]=="long" else "↓空"
        barstr = f"{t['bars']}b({t['bars']*15}m)"
        print(f"{i:>3} {ts:<17} {arrow:<6} {t['entry']:>9.1f} {t['exit']:>9.1f} {t['pnl']*100:>+7.2f}% {t['reason']:<10} {barstr:<6}")
    
    if not trades:
        print("  (无交易)")
    
    # 统计
    wins = [t for t in trades if t["pnl"] > 0]
    longs = [t for t in trades if t["side"]=="long"]
    shorts = [t for t in trades if t["side"]=="short"]
    cum = sum(t["pnl"] for t in trades) * 100
    
    print(f"\n{'='*70}")
    print(f"统计: {len(trades)}笔 | 多{len(longs)} | 空{len(shorts)} | 胜率{len(wins)/len(trades)*100:.1f}%" if trades else "统计: 0笔")
    print(f"累计: {cum:+.2f}% | 复利: {(equity[-1]-1)*100:+.2f}%")
    print(f"均笔: {sum(t['pnl'] for t in trades)/len(trades)*100:+.2f}%" if trades else "")
    print(f"均赢: {sum(t['pnl'] for t in wins)/len(wins)*100:+.2f}%" if wins else "")
    print(f"出场: TP={len([t for t in trades if t['reason']=='TP'])}, SL={len([t for t in trades if t['reason']=='SL'])}, TIMEOUT={len([t for t in trades if t['reason']=='TIMEOUT'])}, OPEN={len([t for t in trades if t['reason']=='OPEN'])}" if trades else "")
    
    # 权益曲线
    if trades:
        print(f"\n权益: {equity[0]:.4f} → {equity[-1]:.4f} ({(equity[-1]-1)*100:+.2f}%)")

if __name__ == "__main__":
    main()
