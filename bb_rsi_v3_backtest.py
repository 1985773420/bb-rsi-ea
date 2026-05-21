#!/usr/bin/env python3
"""BB+RSI v3 完整回测 (OKX history-candles) - 匹配当前 EA 参数"""
import requests, math, json, time
from datetime import datetime, timezone

URL = "https://www.okx.com/api/v5/market/history-candles"
PROXY = "http://127.0.0.1:2080"
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


def fetch(inst="BTC-USDT", days=365):
    target = days * 96
    bars = []
    after = int(time.time() * 1000)

    while len(bars) < target:
        try:
            r = requests.get(
                URL,
                params={"instId": inst, "bar": "15m", "limit": 300, "after": str(after)},
                proxies={"http": PROXY, "https": PROXY},
                timeout=30,
            )
            data = r.json().get("data", [])
            if not data:
                break

            chunk = [
                {
                    "ts": int(row[0]),
                    "c": float(row[4]),
                    "h": float(row[2]),
                    "l": float(row[3]),
                    "o": float(row[1]),
                }
                for row in data
            ]
            bars = chunk + bars
            after = int(data[-1][0])
            time.sleep(0.1)

            if len(bars) % 1000 < 300:
                dt = datetime.fromtimestamp(bars[0]["ts"] / 1000)
                print(f"  {len(bars)}根, 最早{dt.strftime('%Y-%m-%d')}")
        except Exception as e:
            print(f"  [错] {e}")
            time.sleep(1)

    bars.sort(key=lambda x: x["ts"])
    return bars


def calc_indicators(bars):
    cl = [b["c"] for b in bars]
    hi = [b["h"] for b in bars]
    lo = [b["l"] for b in bars]
    n = len(cl)

    bb_u, bb_l = [None] * n, [None] * n
    for i in range(BB_PERIOD - 1, n):
        w = cl[i - BB_PERIOD + 1 : i + 1]
        sma = sum(w) / BB_PERIOD
        std = math.sqrt(sum((x - sma) ** 2 for x in w) / BB_PERIOD)
        bb_u[i] = sma + BB_STD * std
        bb_l[i] = sma - BB_STD * std

    rsi = [None] * n
    for i in range(RSI_PERIOD, n):
        gains = sum(max(cl[j] - cl[j - 1], 0) for j in range(i - RSI_PERIOD + 1, i + 1)) / RSI_PERIOD
        losses = sum(max(cl[j - 1] - cl[j], 0) for j in range(i - RSI_PERIOD + 1, i + 1)) / RSI_PERIOD
        rsi[i] = 100 - 100 / (1 + gains / losses) if losses > 0 else 100

    atr_pct = [None] * n
    for i in range(14, n):
        tr = [
            max(hi[j] - lo[j], abs(hi[j] - cl[j - 1]), abs(lo[j] - cl[j - 1]))
            for j in range(i - 13, i + 1)
        ]
        atr_pct[i] = (sum(tr) / 14) / cl[i] * 100

    valid_atr = [v for v in atr_pct if v is not None]
    atr_mean = sum(valid_atr) / len(valid_atr) if valid_atr else 0.35

    return {"bb_u": bb_u, "bb_l": bb_l, "rsi": rsi, "atr": atr_pct, "atr_mean": atr_mean}


def backtest(bars):
    ind = calc_indicators(bars)
    bb_u, bb_l, rsi, atr, atr_mean = ind["bb_u"], ind["bb_l"], ind["rsi"], ind["atr"], ind["atr_mean"]

    trades = []
    in_pos = None
    entry_px = 0
    entry_bar = 0
    equity = [1.0]
    min_idx = max(BB_PERIOD, RSI_PERIOD, 14) + 1
    n = len(bars)

    for i in range(min_idx, n):
        if in_pos:
            hold_bars = i - entry_bar
            curr_px = bars[i]["c"]
            pnl = (curr_px - entry_px) / entry_px if in_pos == "long" else (entry_px - curr_px) / entry_px

            if pnl >= TP:
                trades.append({"side": in_pos, "pnl": pnl - FEE, "reason": "TP", "ts": bars[i]["ts"], "bar": i})
                equity.append(equity[-1] * (1 + pnl - FEE))
                in_pos = None
                continue
            if pnl <= -SL:
                trades.append({"side": in_pos, "pnl": pnl - FEE, "reason": "SL", "ts": bars[i]["ts"], "bar": i})
                equity.append(equity[-1] * (1 + pnl - FEE))
                in_pos = None
                continue
            if hold_bars >= MAX_BARS:
                trades.append({"side": in_pos, "pnl": pnl - FEE, "reason": "TO", "ts": bars[i]["ts"], "bar": i})
                equity.append(equity[-1] * (1 + pnl - FEE))
                in_pos = None
                continue
            continue

        signal = None
        ep = 0
        for j in range(i - 1, max(i - 4, min_idx - 1), -1):
            if bb_u[j] is None or rsi[j] is None or atr[j] is None:
                continue
            if atr[j] < atr_mean * ATR_VOL_FILTER:
                continue
            cj = bars[j]["c"]
            if cj > bb_u[j] and rsi[j] > RSI_HIGH:
                signal = "short"
                ep = cj
                break
            elif cj < bb_l[j] and rsi[j] < RSI_LOW:
                signal = "long"
                ep = cj
                break

        if signal:
            in_pos = signal
            entry_px = ep
            entry_bar = i

    if in_pos:
        curr_px = bars[-1]["c"]
        pnl = (curr_px - entry_px) / entry_px if in_pos == "long" else (entry_px - curr_px) / entry_px
        trades.append({"side": in_pos, "pnl": pnl - FEE, "reason": "OPEN", "ts": bars[-1]["ts"], "bar": n - 1})

    return trades, equity


def analyze_period(bars, days):
    start = max(0, len(bars) - days * 96)
    pb = bars[start:]
    trades, eq = backtest(pb)

    if not trades:
        return None

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    total_return = (eq[-1] - 1) * 100

    peak = 1.0
    max_drawdown = 0.0
    for v in eq:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        if dd > max_drawdown:
            max_drawdown = dd

    avg_win = sum(t["pnl"] for t in wins) / len(wins) * 100 if wins else 0
    avg_loss = sum(t["pnl"] for t in losses) / len(losses) * 100 if losses else 0
    longs = sum(1 for t in trades if t["side"] == "long")

    tp_count = sum(1 for t in trades if t["reason"] == "TP")
    sl_count = sum(1 for t in trades if t["reason"] == "SL")
    to_count = sum(1 for t in trades if t["reason"] == "TO")

    # 周度分析
    weekly_returns = {}
    for t in trades:
        week = datetime.fromtimestamp(t["ts"] / 1000, tz=timezone.utc).strftime("%Y-W%W")
        weekly_returns[week] = weekly_returns.get(week, 0) + t["pnl"]

    return {
        "days": days,
        "trades": len(trades),
        "win_rate": len(wins) / len(trades) * 100 if trades else 0,
        "total_return": total_return,
        "max_drawdown": max_drawdown * 100,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "longs": longs,
        "shorts": len(trades) - longs,
        "tp_count": tp_count,
        "sl_count": sl_count,
        "to_count": to_count,
        "equity": eq,
        "weekly_returns": weekly_returns,
    }


def main():
    print("=" * 80)
    print("BB+RSI v3 完整回测验证 (OKX history-candles)")
    print("=" * 80)
    print(f"参数: BB({BB_PERIOD},{BB_STD}) RSI({RSI_PERIOD},{RSI_LOW}/{RSI_HIGH}) ATR×{ATR_VOL_FILTER}")
    print(f"止盈:{TP*100}% 止损:{SL*100}% 超时:{MAX_BARS}bar 手续费:{FEE*100}%\n")

    bars = fetch("BTC-USDT", days=180)
    if len(bars) < 500:
        print("❌ 数据不足")
        return

    print(
        f"\n✅ {len(bars)}根 K线 | {datetime.fromtimestamp(bars[0]['ts']/1000).strftime('%Y-%m-%d')} ~ {datetime.fromtimestamp(bars[-1]['ts']/1000).strftime('%Y-%m-%d')}"
    )

    periods = [30, 60, 90, 180, 365]
    results = []

    for days in periods:
        res = analyze_period(bars, days)
        if res:
            results.append(res)
            print(f"\n--- {days}天 ---")
            print(
                f"  交易次数: {res['trades']}笔 | 胜率: {res['win_rate']:.1f}% | 总收益: {res['total_return']:+.2f}%"
            )
            print(f"  多/空: {res['longs']}/{res['shorts']} | TP: {res['tp_count']} SL: {res['sl_count']} TO: {res['to_count']}")
            print(f"  平均赢: {res['avg_win']:+.2f}% | 平均亏: {res['avg_loss']:+.2f}%")
            print(f"  最大回撤: {res['max_drawdown']:.2f}%")

            # 周度统计
            weekly = res["weekly_returns"]
            if weekly:
                pos_weeks = sum(1 for v in weekly.values() if v > 0)
                neg_weeks = sum(1 for v in weekly.values() if v <= 0)
                print(f"  周度盈亏: {len(weekly)}周, {pos_weeks}周盈利 / {neg_weeks}周亏损")

    # 滚动窗口分析
    print("\n" + "=" * 80)
    print("滚动 30 天窗口分析 (过去 365 天)")
    print("=" * 80)
    window_size = 30 * 96
    rolling_returns = []
    for i in range(len(bars) - window_size):
        window = bars[i : i + window_size]
        trades, eq = backtest(window)
        if trades:
            ret = (eq[-1] - 1) * 100
            rolling_returns.append(ret)

    if rolling_returns:
        print(f"  窗口数: {len(rolling_returns)}")
        print(f"  平均收益: {sum(rolling_returns)/len(rolling_returns):+.2f}%")
        print(f"  最好 30 天: {max(rolling_returns):+.2f}%")
        print(f"  最差 30 天: {min(rolling_returns):+.2f}%")
        pos_windows = sum(1 for r in rolling_returns if r > 0)
        print(f"  盈利窗口: {pos_windows}/{len(rolling_returns)} ({pos_windows/len(rolling_returns)*100:.1f}%)")

    # 风险提示
    print("\n" + "=" * 80)
    print("风险分析")
    print("=" * 80)

    if len(results) > 0:
        res_180 = [r for r in results if r["days"] == 180][0] if [r for r in results if r["days"] == 180] else None
        if res_180:
            if res_180["max_drawdown"] > 20:
                print("⚠️  警告: 180 天最大回撤超过 20%")
            if res_180["win_rate"] < 50:
                print("⚠️  注意: 胜率低于 50%")
            if res_180["avg_win"] / abs(res_180["avg_loss"]) < 1.2:
                print("⚠️  注意: 盈亏比偏低 (<1.2)")
    print("\n✅ 回测完成")


if __name__ == "__main__":
    main()
