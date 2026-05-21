#!/usr/bin/env python3
"""
BB+RSI 15m 多方案对比回测
比较不同参数组合在30/60/90天的表现
"""
import requests, math, sys
from datetime import datetime, timezone, timedelta

# ===== Gate.io 数据 =====
GATE_URL = "https://api.gateio.ws/api/v4/spot/candlesticks"
PROXY = "http://127.0.0.1:2080"
TIMEFRAME = "15m"
SYMBOL = "BTC_USDT"

# ===== 交易参数(固定) =====
TP_PCT = 0.008
SL_PCT = 0.004
MAX_BARS = 24
FEE_PCT = 0.0007
POS_SIZE_USDT = 3.0
LEVERAGE = 5

BB_PERIOD = 20
BB_STD = 2
RSI_PERIOD = 10
ATR_VOL_FILTER = 0.8

# ===== 方案定义 =====
VARIANTS = [
    {
        "name": "A-基准(MA730+75/25)",
        "ma730": True, "rsi_high": 75, "rsi_low": 25,
    },
    {
        "name": "B-去MA730(75/25)",
        "ma730": False, "rsi_high": 75, "rsi_low": 25,
    },
    {
        "name": "C-MA730+70/30",
        "ma730": True, "rsi_high": 70, "rsi_low": 30,
    },
    {
        "name": "D-去MA730+70/30",
        "ma730": False, "rsi_high": 70, "rsi_low": 30,
    },
    {
        "name": "E-去MA730+65/35",
        "ma730": False, "rsi_high": 65, "rsi_low": 35,
    },
]

def fetch_bars(limit=1000, to_ts=None):
    """拉取Gate.io K线"""
    params = {"currency_pair": SYMBOL, "interval": TIMEFRAME, "limit": limit}
    if to_ts:
        params["to"] = to_ts
    try:
        r = requests.get(GATE_URL, params=params, proxies={"http": PROXY, "https": PROXY}, timeout=30)
        data = r.json()
        bars = []
        for row in data:
            bars.append({
                "ts": int(row[0]),
                "o": float(row[5]), "h": float(row[3]), "l": float(row[4]),
                "c": float(row[2]), "v": float(row[6]),
            })
        bars.sort(key=lambda x: x["ts"])
        return bars
    except Exception as e:
        print(f"[FETCH ERROR] {e}")
        return []

def fetch_all(limit_bars=6000):
    """分批拉取足够K线"""
    all_bars = []
    while len(all_bars) < limit_bars:
        to_ts = all_bars[0]["ts"] if all_bars else None
        chunk = fetch_bars(1000, to_ts)
        if not chunk:
            break
        if all_bars and chunk[-1]["ts"] >= all_bars[0]["ts"]:
            # 去重
            chunk = [b for b in chunk if b["ts"] < all_bars[0]["ts"]]
        all_bars = chunk + all_bars
        print(f"  已拉取 {len(all_bars)} 根K线...")
        if len(chunk) < 1000:
            break
    return all_bars

def calc_indicators(closes, highs, lows):
    n = len(closes)
    
    # BB(20,2)
    bb_u, bb_l = [None]*n, [None]*n
    for i in range(n):
        if i >= BB_PERIOD - 1:
            w = closes[i-BB_PERIOD+1:i+1]
            sma = sum(w) / BB_PERIOD
            std = math.sqrt(sum((x-sma)**2 for x in w) / BB_PERIOD)
            bb_u[i] = sma + BB_STD * std
            bb_l[i] = sma - BB_STD * std
    
    # RSI(10) - 真正的SMA RSI
    rsi = [None]*n
    gains, losses = [0]*n, [0]*n
    for i in range(1, n):
        ch = closes[i] - closes[i-1]
        gains[i] = max(ch, 0)
        losses[i] = max(-ch, 0)
    for i in range(RSI_PERIOD, n):
        avg_g = sum(gains[i-RSI_PERIOD+1:i+1]) / RSI_PERIOD
        avg_l = sum(losses[i-RSI_PERIOD+1:i+1]) / RSI_PERIOD
        rsi[i] = 100 - 100/(1 + avg_g/avg_l) if avg_l > 0 else 100
    
    # ATR(14)
    tr = [0]*n
    atr_pct = [None]*n
    for i in range(1, n):
        tr[i] = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
    for i in range(14, n):
        atr = sum(tr[i-13:i+1]) / 14
        atr_pct[i] = atr / closes[i] * 100
    
    # ATR均值
    valid_atr = [v for v in atr_pct if v is not None]
    atr_mean = sum(valid_atr) / len(valid_atr) if valid_atr else 0.35
    
    # MA730 (日线用15min近似: 730天*96根/天≈70080根, 用EMA近似)
    # 实际可用窗口内的MA
    ma730 = [None]*n
    ma_period = min(70080, n)
    for i in range(n):
        if i >= ma_period - 1:
            ma730[i] = sum(closes[i-ma_period+1:i+1]) / ma_period
        elif i >= 500:
            # 用可用数据
            available = i + 1
            ma730[i] = sum(closes[0:i+1]) / available
    
    return bb_u, bb_l, rsi, atr_pct, atr_mean, ma730

def backtest(bars, variant, label=""):
    """回测单个方案"""
    bb_u, bb_l, rsi, atr_pct, atr_mean, ma730 = calc_indicators(
        [b["c"] for b in bars],
        [b["h"] for b in bars],
        [b["l"] for b in bars]
    )
    
    use_ma730 = variant["ma730"]
    rsi_h = variant["rsi_high"]
    rsi_l = variant["rsi_low"]
    
    trades = []
    in_position = None  # "long" or "short"
    entry_bar = 0
    entry_px = 0
    
    for i in range(50, len(bars)):
        bar = bars[i]
        c = bar["c"]
        
        if in_position:
            # 检查出场
            bars_held = i - entry_bar
            if in_position == "long":
                pnl_pct = (c - entry_px) / entry_px
            else:
                pnl_pct = (entry_px - c) / entry_px
            
            # 止盈
            if pnl_pct >= TP_PCT:
                trades.append({"entry": entry_px, "exit": c, "side": in_position, 
                              "pnl_pct": pnl_pct - FEE_PCT, "bars": bars_held, "reason": "TP"})
                in_position = None
                continue
            # 止损
            if pnl_pct <= -SL_PCT:
                trades.append({"entry": entry_px, "exit": c, "side": in_position,
                              "pnl_pct": pnl_pct - FEE_PCT, "bars": bars_held, "reason": "SL"})
                in_position = None
                continue
            # 超时
            if bars_held >= MAX_BARS:
                trades.append({"entry": entry_px, "exit": c, "side": in_position,
                              "pnl_pct": pnl_pct - FEE_PCT, "bars": bars_held, "reason": "TIMEOUT"})
                in_position = None
                continue
            # 反向信号出场
            if atr_pct[i] is None or rsi[i] is None:
                continue
            if atr_pct[i] < atr_mean * ATR_VOL_FILTER:
                continue
            
            m730 = ma730[i] if use_ma730 and ma730[i] is not None else None
            if in_position == "long":
                if (m730 is None or c < m730) and c > bb_u[i] and rsi[i] > rsi_h:
                    trades.append({"entry": entry_px, "exit": c, "side": in_position,
                                  "pnl_pct": pnl_pct - FEE_PCT, "bars": bars_held, "reason": "REVERSAL"})
                    in_position = None
                    continue
            else:
                if (m730 is None or c > m730) and c < bb_l[i] and rsi[i] < rsi_l:
                    trades.append({"entry": entry_px, "exit": c, "side": in_position,
                                  "pnl_pct": pnl_pct - FEE_PCT, "bars": bars_held, "reason": "REVERSAL"})
                    in_position = None
                    continue
            continue
        
        # 开仓信号
        if bb_u[i] is None or bb_l[i] is None or rsi[i] is None or atr_pct[i] is None:
            continue
        if atr_pct[i] < atr_mean * ATR_VOL_FILTER:
            continue
        
        m730 = ma730[i] if use_ma730 and ma730[i] is not None else None
        
        # 做空: 上轨+超买(+熊市)
        if (m730 is None or c < m730) and c > bb_u[i] and rsi[i] > rsi_h:
            in_position = "short"
            entry_bar = i
            entry_px = c
        # 做多: 下轨+超卖(+牛市)
        elif (m730 is None or c > m730) and c < bb_l[i] and rsi[i] < rsi_l:
            in_position = "long"
            entry_bar = i
            entry_px = c
    
    # 强制平仓
    if in_position:
        c = bars[-1]["c"]
        if in_position == "long":
            pnl_pct = (c - entry_px) / entry_px
        else:
            pnl_pct = (entry_px - c) / entry_px
        trades.append({"entry": entry_px, "exit": c, "side": in_position,
                      "pnl_pct": pnl_pct - FEE_PCT, "bars": len(bars)-1-entry_bar, "reason": "FORCED"})
    
    return trades

def analyze(trades):
    if not trades:
        return {"total": 0, "cum_pnl": 0, "win_rate": 0, "long": 0, "short": 0}
    
    longs = [t for t in trades if t["side"] == "long"]
    shorts = [t for t in trades if t["side"] == "short"]
    wins = [t for t in trades if t["pnl_pct"] > 0]
    
    cum_pnl = sum(t["pnl_pct"] for t in trades)
    # 复利计算
    equity = 1.0
    for t in trades:
        equity *= (1 + t["pnl_pct"])
    compound = (equity - 1) * 100
    
    return {
        "total": len(trades),
        "cum_pnl": cum_pnl * 100,  # 简单求和%
        "compound": compound,
        "win_rate": len(wins)/len(trades)*100 if trades else 0,
        "long": len(longs),
        "short": len(shorts),
        "avg_pnl": sum(t["pnl_pct"] for t in trades)/len(trades)*100,
        "avg_win": sum(t["pnl_pct"] for t in wins)/len(wins)*100 if wins else 0,
        "avg_loss": sum(t["pnl_pct"] for t in trades if t["pnl_pct"]<=0)/len([t for t in trades if t["pnl_pct"]<=0])*100 if len([t for t in trades if t["pnl_pct"]<=0]) else 0,
        "reasons": {r: len([t for t in trades if t["reason"]==r]) for r in set(t["reason"] for t in trades)},
    }

def main():
    print("="*80)
    print("BB+RSI 15m 多方案对比回测")
    print("="*80)
    
    # 拉取数据
    print("\n📊 拉取Gate.io BTC 15m K线...")
    bars = fetch_all(6000)
    if len(bars) < 500:
        print(f"❌ 数据不足: {len(bars)}根K线")
        return
    
    print(f"✅ 共 {len(bars)} 根K线")
    print(f"   时间范围: {datetime.fromtimestamp(bars[0]['ts']).strftime('%Y-%m-%d %H:%M')} ~ "
          f"{datetime.fromtimestamp(bars[-1]['ts']).strftime('%Y-%m-%d %H:%M')}")
    
    # 分割时间段
    total = len(bars)
    # 每天96根, 30天≈2880, 60天≈5760, 90天≈8640
    periods = {}
    for days in [30, 60, 90]:
        start = max(0, total - days * 96)
        periods[days] = bars[start:]
    
    print("\n" + "="*80)
    print("📈 多方案回测结果")
    print("="*80)
    
    results = {}
    for variant in VARIANTS:
        name = variant["name"]
        print(f"\n{'='*80}")
        print(f"  {name}")
        print(f"{'='*80}")
        
        row_data = {}
        for days, period_bars in periods.items():
            trades = backtest(period_bars, variant, f"{days}d")
            stats = analyze(trades)
            row_data[days] = stats
            
            # 汇总
            print(f"\n  ── {days}天 ({len(period_bars)}根K线) ──")
            print(f"  交易: {stats['total']}笔 | 做多{stats['long']} | 做空{stats['short']}")
            print(f"  胜率: {stats['win_rate']:.1f}%")
            print(f"  累计收益: {stats['cum_pnl']:+.2f}% | 复利: {stats['compound']:+.2f}%")
            print(f"  均笔: {stats['avg_pnl']:+.2f}% | 均赢{stats['avg_win']:+.2f}% | 均亏{stats['avg_loss']:+.2f}%")
            print(f"  出场: {stats['reasons']}")
        
        results[name] = row_data
    
    # 汇总表
    print("\n\n" + "="*80)
    print("📊 汇总对比表")
    print("="*80)
    print(f"{'方案':<30} {'30天交易':>8} {'30天收益':>10} {'30天胜率':>8} {'60天交易':>8} {'60天收益':>10} {'60天胜率':>8} {'90天交易':>8} {'90天收益':>10} {'90天胜率':>8}")
    print("-"*115)
    
    for name, row in results.items():
        s30 = row[30]; s60 = row[60]; s90 = row[90]
        print(f"{name:<30} {s30['total']:>8} {s30['compound']:>+9.2f}% {s30['win_rate']:>7.1f}% "
              f"{s60['total']:>8} {s60['compound']:>+9.2f}% {s60['win_rate']:>7.1f}% "
              f"{s90['total']:>8} {s90['compound']:>+9.2f}% {s90['win_rate']:>7.1f}%")
    
    # 找出最佳方案
    print("\n" + "="*80)
    print("🏆 综合评分 (总分 = 30d复利×2 + 60d复利 + 90d复利)")
    print("="*80)
    best_score = -999; best_name = ""
    for name, row in results.items():
        score = row[30]["compound"]*2 + row[60]["compound"] + row[90]["compound"]
        total_trades = row[30]["total"] + row[60]["total"] + row[90]["total"]
        print(f"  {name:<30} 得分: {score:+.2f}  |  总交易: {total_trades}笔")
        if score > best_score:
            best_score = score
            best_name = name
    
    print(f"\n  ✅ 最佳方案: {best_name}")

if __name__ == "__main__":
    main()
