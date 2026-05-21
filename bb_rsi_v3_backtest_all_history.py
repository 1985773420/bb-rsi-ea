#!/usr/bin/env python3
"""BB+RSI v3 完整回测 (OKX 所有可用历史数据)"""
import requests, math, json, time
from datetime import datetime, timezone

URL = "https://www.okx.com/api/v5/market/history-candles"
PROXY = {"http": "http://127.0.0.1:2080", "https": "http://127.0.0.1:2080"}

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

def fetch_all_historical(inst_id="BTC-USDT", bar="15m"):
    """拉取所有可用历史K线"""
    target_end = int(time.time() * 1000)
    all_bars = []
    limit = 300
    iterations = 0

    print(f"正在拉取 OKX {inst_id} {bar} 所有可用历史数据...", flush=True)

    while True:
        try:
            params = {
                "instId": inst_id,
                "bar": bar,
                "limit": limit,
                "after": str(target_end)
            }
            res = requests.get(URL, params=params, proxies=PROXY, timeout=30)
            data = res.json().get("data", [])

            if not data or len(data) == 0:
                print("  已拉取完所有可用数据！", flush=True)
                break

            for row in data:
                bar_data = {
                    "ts": int(row[0]),
                    "o": float(row[1]),
                    "h": float(row[2]),
                    "l": float(row[3]),
                    "c": float(row[4])
                }
                all_bars.append(bar_data)

            target_end = int(data[-1][0])
            iterations += 1
            time.sleep(0.1)

            if iterations % 10 == 0 or len(all_bars) % 3000 < 300:
                dt = datetime.fromtimestamp(all_bars[-1]["ts"] / 1000, tz=timezone.utc)
                print(f"  已获取 {len(all_bars)} 根，最早 {dt.strftime('%Y-%m-%d %H:%M')}", flush=True)

        except Exception as e:
            print(f"  拉取错误: {e}", flush=True)
            time.sleep(2)
            continue

    all_bars.sort(key=lambda x: x["ts"])
    return all_bars

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
    """策略回测"""
    bb_upper = indicators["bb_upper"]
    bb_lower = indicators["bb_lower"]
    rsi = indicators["rsi"]
    atr_pct = indicators["atr_pct"]
    atr_mean = indicators["atr_mean"]

    trades = []
    equity_curve = [1.0]
    in_position = None
    entry_price = 0
    entry_bar = 0

    min_idx = max(BB_PERIOD, RSI_PERIOD, 14) + 1

    for i in range(min_idx, len(bars)):
        if in_position:
            current_close = bars[i]["c"]
            hold_bars = i - entry_bar
            if in_position == "long":
                pnl_pct = (current_close - entry_price) / entry_price
            else:
                pnl_pct = (entry_price - current_close) / entry_price

            if pnl_pct >= TP:
                trades.append({
                    "side": in_position,
                    "pnl": pnl_pct - FEE,
                    "reason": "TP",
                    "entry_bar": entry_bar,
                    "exit_bar": i,
                    "ts": bars[i]["ts"]
                })
                equity_curve.append(equity_curve[-1] * (1 + pnl_pct - FEE))
                in_position = None
            elif pnl_pct <= -SL:
                trades.append({
                    "side": in_position,
                    "pnl": pnl_pct - FEE,
                    "reason": "SL",
                    "entry_bar": entry_bar,
                    "exit_bar": i,
                    "ts": bars[i]["ts"]
                })
                equity_curve.append(equity_curve[-1] * (1 + pnl_pct - FEE))
                in_position = None
            elif hold_bars >= MAX_BARS:
                trades.append({
                    "side": in_position,
                    "pnl": pnl_pct - FEE,
                    "reason": "TO",
                    "entry_bar": entry_bar,
                    "exit_bar": i,
                    "ts": bars[i]["ts"]
                })
                equity_curve.append(equity_curve[-1] * (1 + pnl_pct - FEE))
                in_position = None
            continue

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
            if atr_pct[j] < atr_mean * ATR_VOL_FILTER:
                continue
            close_j = bars[j]["c"]
            if close_j > bb_upper[j] and rsi[j] > RSI_HIGH:
                signal = "short"
                signal_bar = j
                break
            elif close_j < bb_lower[j] and rsi[j] < RSI_LOW:
                signal = "long"
                signal_bar = j
                break

        if signal:
            in_position = signal
            entry_price = bars[signal_bar]["c"]
            entry_bar = i

    if in_position:
        current_close = bars[-1]["c"]
        if in_position == "long":
            pnl_pct = (current_close - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - current_close) / entry_price
        trades.append({
            "side": in_position,
            "pnl": pnl_pct - FEE,
            "reason": "OPEN",
            "entry_bar": entry_bar,
            "exit_bar": len(bars) - 1,
            "ts": bars[-1]["ts"]
        })

    return trades, equity_curve

def max_consecutive_loses(trades):
    """计算最大连续亏损笔数"""
    max_streak = 0
    current_streak = 0
    for t in trades:
        if t["pnl"] <= 0:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0
    return max_streak

def main():
    # 拉取所有数据
    bars = fetch_all_historical(inst_id="BTC-USDT", bar="15m")

    if len(bars) < 1000:
        print("数据不足，无法回测")
        return

    # 保存数据到本地，避免重复拉取
    with open("/tmp/btc_15m_all_okx.json", "w") as f:
        json.dump(bars, f)
    print(f"\n✅ 数据已保存到 /tmp/btc_15m_all_okx.json ({len(bars)} 根)")

    # 计算指标
    print("\n计算技术指标...")
    indicators = calc_indicators(bars)

    # 回测
    print("运行策略回测...")
    trades, equity_curve = backtest_strategy(bars, indicators)

    # 分析
    print("\n" + "=" * 90)
    print("📊 BB+RSI v3 完整回测结果 (OKX 所有可用历史数据)")
    print("=" * 90)
    start_dt = datetime.fromtimestamp(bars[0]["ts"] / 1000, tz=timezone.utc)
    end_dt = datetime.fromtimestamp(bars[-1]["ts"] / 1000, tz=timezone.utc)
    days_covered = (end_dt - start_dt).total_seconds() / 86400
    print(f"回测时间: {start_dt.strftime('%Y-%m-%d')} → {end_dt.strftime('%Y-%m-%d')} ({days_covered:.1f} 天)")
    print(f"K线数量: {len(bars)} 根")

    # 基本统计
    total_return = (equity_curve[-1] - 1) * 100
    win_trades = [t for t in trades if t["pnl"] > 0]
    lose_trades = [t for t in trades if t["pnl"] <= 0]
    win_rate = len(win_trades) / len(trades) * 100 if trades else 0

    # 最大回撤
    peak = 1.0
    max_drawdown = 0.0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak
        if dd > max_drawdown:
            max_drawdown = dd

    # 其他统计
    tp_count = sum(1 for t in trades if t["reason"] == "TP")
    sl_count = sum(1 for t in trades if t["reason"] == "SL")
    to_count = sum(1 for t in trades if t["reason"] == "TO")
    long_count = sum(1 for t in trades if t["side"] == "long")
    short_count = len(trades) - long_count

    avg_win = sum(t["pnl"] for t in win_trades) / len(win_trades) * 100 if win_trades else 0
    avg_loss = sum(t["pnl"] for t in lose_trades) / len(lose_trades) * 100 if lose_trades else 0

    print(f"\n📈 交易统计:")
    print(f"  总交易次数: {len(trades)}")
    print(f"  胜率: {win_rate:.1f}%")
    print(f"  多/空: {long_count}/{short_count}")
    print(f"  止盈/止损/超时: {tp_count}/{sl_count}/{to_count}")

    print(f"\n💰 收益统计:")
    print(f"  总收益率: {total_return:+.2f}%")
    print(f"  平均盈利: {avg_win:+.2f}%")
    print(f"  平均亏损: {avg_loss:+.2f}%")
    print(f"  盈亏比: {abs(avg_win/avg_loss):.2f}" if avg_loss != 0 else "  盈亏比: N/A")
    print(f"  年化收益率: {total_return/(days_covered/365):+.2f}%" if days_covered > 0 else "  年化收益率: N/A")

    print(f"\n⚠️ 风险统计:")
    print(f"  最大回撤: {max_drawdown*100:.2f}%")
    print(f"  最大连续亏损笔数: {max_consecutive_loses(trades)}")

    print("=" * 90)

if __name__ == "__main__":
    main()
