#!/usr/bin/env python3
"""BB+RSI v3 最近7天回测 详细统计"""
import math, json, time
from datetime import datetime, timezone, timedelta

DATA_PATH = "/tmp/btc_15m_all_okx.json"

# ============== 策略参数 ==============
TP = 0.005
SL = 0.003
MAX_BARS = 24
FEE = 0.0007
BB_PERIOD = 20
BB_STD = 2
RSI_PERIOD = 7
RSI_HIGH = 70
RSI_LOW = 30
ATR_VOL_FILTER = 0.5

def load_data():
    """加载全量数据并筛选最近7天"""
    print("加载全量数据...", flush=True)
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
    
    # 筛选最近30天的数据
    now_ts = time.time() * 1000
    thirty_days_ago_ts = now_ts - (30 * 86400 * 1000)
    recent_bars = [b for b in bars if b["ts"] >= thirty_days_ago_ts]
    
    print(f"✅ 筛选最近30天数据：共 {len(recent_bars)} 根K线", flush=True)
    start_dt = datetime.fromtimestamp(recent_bars[0]["ts"] / 1000, tz=timezone.utc)
    end_dt = datetime.fromtimestamp(recent_bars[-1]["ts"] / 1000, tz=timezone.utc)
    print(f"时间范围：{start_dt.strftime('%Y-%m-%d %H:%M')} → {end_dt.strftime('%Y-%m-%d %H:%M')}", flush=True)
    
    return recent_bars

def calc_indicators(bars):
    """计算技术指标"""
    n = len(bars)
    closes = [b["c"] for b in bars]
    highs = [b["h"] for b in bars]
    lows = [b["l"] for b in bars]

    bb_upper = [None] * n
    bb_lower = [None] * n
    for i in range(BB_PERIOD - 1, n):
        window = closes[i - BB_PERIOD + 1 : i + 1]
        sma = sum(window) / BB_PERIOD
        std = math.sqrt(sum((x - sma) ** 2 for x in window) / BB_PERIOD)
        bb_upper[i] = sma + BB_STD * std
        bb_lower[i] = sma - BB_STD * std

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

        if i >= RSI_PERIOD:
            avg_gain = sum(gains[i - RSI_PERIOD + 1 : i + 1]) / RSI_PERIOD
            avg_loss = sum(losses[i - RSI_PERIOD + 1 : i + 1]) / RSI_PERIOD
            if avg_loss == 0:
                rsi[i] = 100
            else:
                rs = avg_gain / avg_loss
                rsi[i] = 100 - (100 / (1 + rs))

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

def backtest_strategy(bars, indicators):
    """策略回测，返回详细交易记录"""
    bb_upper = indicators["bb_upper"]
    bb_lower = indicators["bb_lower"]
    rsi = indicators["rsi"]
    atr_pct = indicators["atr_pct"]
    atr_mean = indicators["atr_mean"]

    trades = []
    in_position = None
    entry_price = 0
    entry_bar = 0
    entry_ts = 0

    min_idx = max(BB_PERIOD, RSI_PERIOD, 14) + 1

    for i in range(min_idx, len(bars)):
        current_bar = bars[i]
        if in_position:
            current_close = current_bar["c"]
            hold_bars = i - entry_bar
            if in_position == "long":
                pnl_pct = (current_close - entry_price) / entry_price
            else:
                pnl_pct = (entry_price - current_close) / entry_price

            # 平仓判断
            close_reason = None
            close_price = None
            if pnl_pct >= TP:
                close_reason = "止盈"
                close_price = entry_price * (1 + TP) if in_position == "long" else entry_price * (1 - TP)
            elif pnl_pct <= -SL:
                close_reason = "止损"
                close_price = entry_price * (1 - SL) if in_position == "long" else entry_price * (1 + SL)
            elif hold_bars >= MAX_BARS:
                close_reason = "超时平仓"
                close_price = current_close

            if close_reason:
                net_pnl_pct = pnl_pct - FEE
                trades.append({
                    "开仓时间": datetime.fromtimestamp(entry_ts / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M'),
                    "平仓时间": datetime.fromtimestamp(current_bar["ts"] / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M'),
                    "方向": "做多" if in_position == "long" else "做空",
                    "开仓价格": round(entry_price, 2),
                    "平仓价格": round(close_price, 2),
                    "盈亏%": round(net_pnl_pct * 100, 2),
                    "平仓原因": close_reason,
                    "持仓K线数": hold_bars
                })
                in_position = None
            continue

        # 开仓信号判断
        signal = None
        signal_bar_idx = None
        for j in range(i - 1, max(i - 4, min_idx - 1), -1):
            if (
                bb_upper[j] is None or
                bb_lower[j] is None or
                rsi[j] is None or
                atr_pct[j] is None
            ):
                continue
            if atr_pct[j] < atr_mean * ATR_VOL_FILTER:
                continue
            close_j = bars[j]["c"]
            if close_j > bb_upper[j] and rsi[j] > RSI_HIGH:
                signal = "short"
                signal_bar_idx = j
                break
            elif close_j < bb_lower[j] and rsi[j] < RSI_LOW:
                signal = "long"
                signal_bar_idx = j
                break

        if signal:
            in_position = signal
            entry_price = bars[signal_bar_idx]["c"]
            entry_bar = i
            entry_ts = current_bar["ts"]

    # 处理未平仓
    if in_position:
        current_close = bars[-1]["c"]
        if in_position == "long":
            pnl_pct = (current_close - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - current_close) / entry_price
        net_pnl_pct = pnl_pct - FEE
        trades.append({
            "开仓时间": datetime.fromtimestamp(entry_ts / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M'),
            "平仓时间": datetime.fromtimestamp(bars[-1]["ts"] / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M'),
            "方向": "做多" if in_position == "long" else "做空",
            "开仓价格": round(entry_price, 2),
            "平仓价格": round(current_close, 2),
            "盈亏%": round(net_pnl_pct * 100, 2),
            "平仓原因": "持仓中",
            "持仓K线数": len(bars) - entry_bar
        })

    return trades

def analyze_trades(trades):
    """分析交易记录"""
    if not trades:
        print("\n❌ 没有交易记录")
        return

    print("\n" + "=" * 120)
    print("📋 最近7天交易明细")
    print("=" * 120)
    print(f"{'开仓时间':<18} {'平仓时间':<18} {'方向':<4} {'开仓价':<10} {'平仓价':<10} {'盈亏%':<8} {'平仓原因':<10} {'持仓K线数':<10}")
    print("-" * 120)
    for t in trades:
        color = "\033[32m" if t["盈亏%"] > 0 else "\033[31m" if t["盈亏%"] < 0 else ""
        reset = "\033[0m"
        print(f"{t['开仓时间']:<18} {t['平仓时间']:<18} {t['方向']:<4} {t['开仓价格']:<10} {t['平仓价格']:<10} {color}{t['盈亏%']:<8}{reset} {t['平仓原因']:<10} {t['持仓K线数']:<10}")

    # 汇总统计
    total_trades = len(trades)
    win_trades = [t for t in trades if t["盈亏%"] > 0]
    lose_trades = [t for t in trades if t["盈亏%"] < 0]
    even_trades = [t for t in trades if t["盈亏%"] == 0]
    win_rate = len(win_trades) / total_trades * 100 if total_trades > 0 else 0

    total_profit = sum(t["盈亏%"] for t in win_trades)
    total_loss = sum(t["盈亏%"] for t in lose_trades)
    net_profit = total_profit + total_loss

    max_win = max([t["盈亏%"] for t in win_trades]) if win_trades else 0
    max_loss = min([t["盈亏%"] for t in lose_trades]) if lose_trades else 0

    avg_win = total_profit / len(win_trades) if win_trades else 0
    avg_loss = total_loss / len(lose_trades) if lose_trades else 0

    tp_count = sum(1 for t in trades if t["平仓原因"] == "止盈")
    sl_count = sum(1 for t in trades if t["平仓原因"] == "止损")
    to_count = sum(1 for t in trades if t["平仓原因"] == "超时平仓")
    open_count = sum(1 for t in trades if t["平仓原因"] == "持仓中")

    print("\n" + "=" * 120)
    print("📊 最近7天回测汇总")
    print("=" * 120)
    print(f"总交易笔数：{total_trades}")
    print(f"盈利笔数：{len(win_trades)} | 亏损笔数：{len(lose_trades)} | 平盘：{len(even_trades)} | 持仓中：{open_count}")
    print(f"胜率：{win_rate:.1f}%")
    print(f"\n止盈笔数：{tp_count} | 止损笔数：{sl_count} | 超时平仓笔数：{to_count}")
    print(f"\n总盈利：{total_profit:.2f}% | 总亏损：{total_loss:.2f}% | 净盈利：{net_profit:.2f}%")
    print(f"平均每笔盈利：{avg_win:.2f}% | 平均每笔亏损：{avg_loss:.2f}%")
    print(f"最大单笔盈利：{max_win:.2f}% | 最大单笔亏损：{max_loss:.2f}%")
    print("\n" + "=" * 120)

def main():
    recent_bars = load_data()
    if len(recent_bars) < 100:
        print("❌ 数据不足，无法回测")
        return

    print("\n计算技术指标...", flush=True)
    indicators = calc_indicators(recent_bars)

    print("运行回测...", flush=True)
    trades = backtest_strategy(recent_bars, indicators)

    analyze_trades(trades)

if __name__ == "__main__":
    main()
