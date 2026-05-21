#!/usr/bin/env python3
"""参数稳定性对比测试：不同ATR阈值、止盈止损组合表现"""
import math, json, time
from datetime import datetime, timezone

DATA_PATH = "/tmp/btc_15m_all_okx.json"

# 要测试的参数组合
PARAMS_COMBINATIONS = [
    {"name": "当前参数", "tp": 0.005, "sl": 0.003, "atr_filter": 0.5, "bb_period":20, "rsi_period":7, "rsi_high":70, "rsi_low":30},
    {"name": "ATR提升到0.6", "tp": 0.005, "sl": 0.003, "atr_filter": 0.6, "bb_period":20, "rsi_period":7, "rsi_high":70, "rsi_low":30},
    {"name": "ATR降低到0.4", "tp": 0.005, "sl": 0.003, "atr_filter": 0.4, "bb_period":20, "rsi_period":7, "rsi_high":70, "rsi_low":30},
    {"name": "止盈0.6止损0.4", "tp": 0.006, "sl": 0.004, "atr_filter": 0.5, "bb_period":20, "rsi_period":7, "rsi_high":70, "rsi_low":30},
    {"name": "止盈0.4止损0.25", "tp": 0.004, "sl": 0.0025, "atr_filter": 0.5, "bb_period":20, "rsi_period":7, "rsi_high":70, "rsi_low":30},
    {"name": "RSI阈值65/35", "tp": 0.005, "sl": 0.003, "atr_filter": 0.5, "bb_period":20, "rsi_period":7, "rsi_high":65, "rsi_low":35},
]

def load_recent_180d_data():
    """加载最近180天数据"""
    with open(DATA_PATH, "r") as f:
        raw_data = json.load(f)
    
    bars = []
    for row in raw_data:
        bars.append({
            "ts": int(row[0]),
            "o": float(row[1]),
            "h": float(row[2]),
            "l": float(row[3]),
            "c": float(row[4])
        })
    bars.sort(key=lambda x: x["ts"])
    
    # 取最近180天
    now_ts = time.time() * 1000
    one_eighty_days_ago = now_ts - 180 * 86400 * 1000
    recent_bars = [b for b in bars if b["ts"] >= one_eighty_days_ago]
    return recent_bars

def calc_indicators(bars, params):
    """计算技术指标"""
    n = len(bars)
    closes = [b["c"] for b in bars]
    highs = [b["h"] for b in bars]
    lows = [b["l"] for b in bars]
    bb_period = params["bb_period"]
    rsi_period = params["rsi_period"]

    # 布林带
    bb_upper = [None] * n
    bb_lower = [None] * n
    for i in range(bb_period - 1, n):
        window = closes[i - bb_period + 1 : i + 1]
        sma = sum(window) / bb_period
        std = math.sqrt(sum((x - sma) ** 2 for x in window) / bb_period)
        bb_upper[i] = sma + 2 * std
        bb_lower[i] = sma - 2 * std

    # RSI
    rsi = [None] * n
    gains = []
    losses = []
    for i in range(n):
        if i == 0:
            gains.append(0)
            losses.append(0)
        else:
            change = closes[i] - closes[i - 1]
            gains.append(max(change, 0))
            losses.append(max(-change, 0))

        if i >= rsi_period:
            avg_gain = sum(gains[i - rsi_period + 1 : i + 1]) / rsi_period
            avg_loss = sum(losses[i - rsi_period + 1 : i + 1]) / rsi_period
            if avg_loss == 0:
                rsi[i] = 100
            else:
                rs = avg_gain / avg_loss
                rsi[i] = 100 - (100 / (1 + rs))

    # ATR%
    atr_pct = [None] * n
    tr_list = []
    for i in range(n):
        if i == 0:
            tr = highs[i] - lows[i]
        else:
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1])
            )
        tr_list.append(tr)

        if i >= 14:
            atr = sum(tr_list[i - 13 : i + 1]) / 14
            atr_pct[i] = (atr / closes[i]) * 100

    valid_atr = [x for x in atr_pct if x is not None]
    atr_mean = sum(valid_atr) / len(valid_atr) if valid_atr else 0.35

    return {
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
        "rsi": rsi,
        "atr_pct": atr_pct,
        "atr_mean": atr_mean
    }

def backtest(bars, indicators, params):
    """回测指定参数"""
    bb_upper = indicators["bb_upper"]
    bb_lower = indicators["bb_lower"]
    rsi = indicators["rsi"]
    atr_pct = indicators["atr_pct"]
    atr_mean = indicators["atr_mean"]
    tp = params["tp"]
    sl = params["sl"]
    atr_filter = params["atr_filter"]
    rsi_high = params["rsi_high"]
    rsi_low = params["rsi_low"]

    trades = []
    equity_curve = [1.0]
    in_position = None
    entry_price = 0
    entry_bar = 0

    min_idx = max(20, 7, 14) + 1

    for i in range(min_idx, len(bars)):
        if in_position:
            current_close = bars[i]["c"]
            hold_bars = i - entry_bar
            if in_position == "long":
                pnl_pct = (current_close - entry_price) / entry_price
            else:
                pnl_pct = (entry_price - current_close) / entry_price

            if pnl_pct >= tp:
                trades.append({"pnl": pnl_pct - 0.0007}) # 手续费万7
                equity_curve.append(equity_curve[-1] * (1 + pnl_pct - 0.0007))
                in_position = None
            elif pnl_pct <= -sl:
                trades.append({"pnl": pnl_pct - 0.0007})
                equity_curve.append(equity_curve[-1] * (1 + pnl_pct - 0.0007))
                in_position = None
            elif hold_bars >= 24:
                trades.append({"pnl": pnl_pct - 0.0007})
                equity_curve.append(equity_curve[-1] * (1 + pnl_pct - 0.0007))
                in_position = None
            continue

        # 开仓信号
        signal = None
        signal_bar = None
        for j in range(i - 1, max(i - 4, min_idx - 1), -1):
            if (
                bb_upper[j] is None or
                bb_lower[j] is None or
                rsi[j] is None or
                atr_pct[j] is None
            ):
                continue
            if atr_pct[j] < atr_mean * atr_filter:
                continue
            close_j = bars[j]["c"]
            if close_j > bb_upper[j] and rsi[j] > rsi_high:
                signal = "short"
                signal_bar = j
                break
            elif close_j < bb_lower[j] and rsi[j] < rsi_low:
                signal = "long"
                signal_bar = j
                break

        if signal:
            in_position = signal
            entry_price = bars[signal_bar]["c"]
            entry_bar = i

    # 统计指标
    total_return = (equity_curve[-1] - 1) * 100
    win_trades = [t for t in trades if t["pnl"] > 0]
    lose_trades = [t for t in trades if t["pnl"] <= 0]
    win_rate = len(win_trades)/len(trades)*100 if trades else 0

    # 最大回撤
    peak = 1.0
    max_drawdown = 0.0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq)/peak
        if dd > max_drawdown:
            max_drawdown = dd

    # 盈亏比
    avg_win = sum(t["pnl"] for t in win_trades)/len(win_trades)*100 if win_trades else 0
    avg_loss = sum(t["pnl"] for t in lose_trades)/len(lose_trades)*100 if lose_trades else 0
    profit_loss_ratio = abs(avg_win/avg_loss) if avg_loss != 0 else 0

    return {
        "total_trades": len(trades),
        "total_return": total_return,
        "win_rate": win_rate,
        "max_drawdown": max_drawdown*100,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_loss_ratio": profit_loss_ratio,
    }

def main():
    print("加载最近180天数据...")
    bars = load_recent_180d_data()
    print(f"共 {len(bars)} 根K线，时间范围：{datetime.fromtimestamp(bars[0]['ts']/1000).strftime('%Y-%m-%d')} → {datetime.fromtimestamp(bars[-1]['ts']/1000).strftime('%Y-%m-%d')}")

    print("\n" + "="*120)
    print(f"{'参数名称':<20} {'总交易':<8} {'总收益':<10} {'胜率':<8} {'最大回撤':<10} {'平均盈利':<10} {'平均亏损':<10} {'盈亏比':<8}")
    print("="*120)

    results = []
    for params in PARAMS_COMBINATIONS:
        indicators = calc_indicators(bars, params)
        res = backtest(bars, indicators, params)
        results.append((params["name"], res))

        color = "\033[32m" if res["total_return"] > 0 else "\033[31m"
        reset = "\033[0m"
        print(f"{params['name']:<20} {res['total_trades']:<8} {color}{res['total_return']:<10.2f}{reset} {res['win_rate']:<8.1f} {res['max_drawdown']:<10.2f} {res['avg_win']:<10.2f} {res['avg_loss']:<10.2f} {res['profit_loss_ratio']:<8.2f}")

    print("\n" + "="*120)
    print("✅ 参数对比测试完成")
    print("\n📝 结论：")
    best = max(results, key=lambda x: x[1]["total_return"])
    print(f"   最优参数：{best[0]}，总收益：{best[1]['total_return']:.2f}%，最大回撤：{best[1]['max_drawdown']:.2f}%，胜率：{best[1]['win_rate']:.1f}%")
    current = [r for r in results if r[0] == "当前参数"][0]
    print(f"   当前参数：总收益：{current[1]['total_return']:.2f}%，最大回撤：{current[1]['max_drawdown']:.2f}%，胜率：{current[1]['win_rate']:.1f}%")
    print("="*120)

if __name__ == "__main__":
    main()
