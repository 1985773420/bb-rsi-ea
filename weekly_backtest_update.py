#!/usr/bin/env python3
"""每周回测更新 v2：从SQLite读取数据 → 回测 → 保存结果"""
import sys, os, math, json, time, requests
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datastore as db

OUTPUT_PATH = "/tmp/bb_rsi_backtest_results.json"

# ============== 策略参数 ==============
TP = 0.005; SL = 0.003; MAX_BARS = 24; FEE = 0.0007
BB_PERIOD = 20; BB_STD = 2; RSI_PERIOD = 7
RSI_HIGH = 70; RSI_LOW = 30; ATR_VOL_FILTER = 0.5

def fetch_and_store():
    """从REST增量拉取新数据写入SQLite"""
    print("[fetch] 增量拉取 OKX 数据...", flush=True)
    latest_db = db.get_latest_ts()
    target_end = int(time.time() * 1000)
    total_new = 0
    
    if latest_db == 0:
        target_end = int(time.time() * 1000)
    else:
        target_end = int(time.time() * 1000)
    
    while True:
        try:
            r = requests.get(
                "https://www.okx.com/api/v5/market/history-candles",
                params={"instId": "BTC-USDT", "bar": "15m", "limit": 300, "after": str(target_end)},
                proxies={"http": "http://127.0.0.1:2080", "https": "http://127.0.0.1:2080"},
                timeout=30
            )
            data = r.json().get("data", [])
            if not data: break
            
            n = db.insert_candles(data)
            total_new += n
            target_end = int(data[-1][0])
            time.sleep(0.1)
            
            # 检查是否已覆盖已有数据
            if int(data[-1][0]) <= latest_db:
                break
        except Exception as e:
            print(f"  [fetch error] {e}", flush=True)
            time.sleep(2)
            continue
    
    print(f"[fetch] 新增 {total_new} 根，总计 {db.count()} 根", flush=True)

def load_all_bars():
    """从SQLite加载所有数据"""
    print("[load] 从 SQLite 加载全量数据...", flush=True)
    bars = db.get_range(0)
    print(f"[load] 加载 {len(bars)} 根", flush=True)
    return bars

def calc_indicators(bars):
    n = len(bars)
    closes = [b["c"] for b in bars]; highs = [b["h"] for b in bars]; lows = [b["l"] for b in bars]

    bb_upper = [None] * n; bb_lower = [None] * n
    for i in range(BB_PERIOD - 1, n):
        window = closes[i - BB_PERIOD + 1 : i + 1]
        sma = sum(window) / BB_PERIOD; std = math.sqrt(sum((x - sma) ** 2 for x in window) / BB_PERIOD)
        bb_upper[i] = sma + BB_STD * std; bb_lower[i] = sma - BB_STD * std

    rsi = [None] * n; gains = []; losses = []
    for i in range(n):
        if i == 0: gains.append(0); losses.append(0)
        else: change = closes[i] - closes[i - 1]; gains.append(max(change, 0)); losses.append(max(-change, 0))
        if i >= RSI_PERIOD:
            avg_gain = sum(gains[i - RSI_PERIOD + 1 : i + 1]) / RSI_PERIOD
            avg_loss = sum(losses[i - RSI_PERIOD + 1 : i + 1]) / RSI_PERIOD
            rsi[i] = 100 - 100 / (1 + avg_gain / avg_loss) if avg_loss > 0 else 100

    atr_pct = [None] * n; tr_list = []
    for i in range(n):
        if i == 0: tr = highs[i] - lows[i]
        else: tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        tr_list.append(tr)
        if i >= 14: atr_pct[i] = (sum(tr_list[i - 13 : i + 1]) / 14) / closes[i] * 100

    valid_atr = [x for x in atr_pct if x is not None]
    atr_mean = sum(valid_atr) / len(valid_atr) if valid_atr else 0.35
    return {"bb_upper": bb_upper, "bb_lower": bb_lower, "rsi": rsi, "atr_pct": atr_pct, "atr_mean": atr_mean}

def backtest(bars, indicators):
    bb_upper = indicators["bb_upper"]; bb_lower = indicators["bb_lower"]
    rsi = indicators["rsi"]; atr_pct = indicators["atr_pct"]; atr_mean = indicators["atr_mean"]

    trades = []; equity_curve = [1.0]
    in_pos = None; ep = 0; eb = 0; ets = 0
    min_idx = max(BB_PERIOD, RSI_PERIOD, 14) + 1

    for i in range(min_idx, len(bars)):
        if in_pos:
            c = bars[i]["c"]; h = i - eb
            pnl = (c - ep) / ep if in_pos == "long" else (ep - c) / ep
            if pnl >= TP:
                trades.append({"pnl": pnl - FEE, "ts": bars[i]["ts"], "entry_ts": ets, "reason": "TP"})
                equity_curve.append(equity_curve[-1] * (1 + pnl - FEE)); in_pos = None
            elif pnl <= -SL:
                trades.append({"pnl": pnl - FEE, "ts": bars[i]["ts"], "entry_ts": ets, "reason": "SL"})
                equity_curve.append(equity_curve[-1] * (1 + pnl - FEE)); in_pos = None
            elif h >= MAX_BARS:
                trades.append({"pnl": pnl - FEE, "ts": bars[i]["ts"], "entry_ts": ets, "reason": "TO"})
                equity_curve.append(equity_curve[-1] * (1 + pnl - FEE)); in_pos = None
            continue

        signal = None; sb = None
        for j in range(i - 1, max(i - 4, min_idx - 1), -1):
            if bb_upper[j] is None or bb_lower[j] is None or rsi[j] is None or atr_pct[j] is None: continue
            if atr_pct[j] < atr_mean * ATR_VOL_FILTER: continue
            cj = bars[j]["c"]
            if cj > bb_upper[j] and rsi[j] > RSI_HIGH: signal = "short"; sb = j; break
            elif cj < bb_lower[j] and rsi[j] < RSI_LOW: signal = "long"; sb = j; break

        if signal: in_pos = signal; ep = bars[sb]["c"]; eb = i; ets = bars[i]["ts"]

    return trades, equity_curve

def analyze(trades, equity_curve):
    if not trades: return {}
    total_return = (equity_curve[-1] - 1) * 100
    win_trades = [t for t in trades if t["pnl"] > 0]
    lose_trades = [t for t in trades if t["pnl"] <= 0]
    win_rate = len(win_trades) / len(trades) * 100
    peak = 1.0; max_drawdown = 0.0
    for eq in equity_curve:
        if eq > peak: peak = eq
        dd = (peak - eq) / peak
        if dd > max_drawdown: max_drawdown = dd
    avg_win = sum(t["pnl"] for t in win_trades) / len(win_trades) * 100 if win_trades else 0
    avg_loss = sum(t["pnl"] for t in lose_trades) / len(lose_trades) * 100 if lose_trades else 0
    profit_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0
    return {
        "total_trades": len(trades), "total_return": round(total_return, 2),
        "win_rate": round(win_rate, 1), "max_drawdown": round(max_drawdown * 100, 2),
        "avg_win": round(avg_win, 2), "avg_loss": round(avg_loss, 2),
        "profit_loss_ratio": round(profit_loss_ratio, 2)
    }

def main():
    print(f"=== 每周回测 v2 {datetime.now().strftime('%Y-%m-%d %H:%M')} ===", flush=True)

    # 增量拉取
    fetch_and_store()

    # 加载全量
    bars = load_all_bars()
    if len(bars) < 1000:
        print("数据不足", flush=True); return

    # 计算 + 回测
    print("[bt] 计算指标 + 回测...", flush=True)
    indicators = calc_indicators(bars)
    trades, equity_curve = backtest(bars, indicators)

    # 全历史
    full_result = analyze(trades, equity_curve)
    start_dt = datetime.fromtimestamp(bars[0]["ts"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    end_dt = datetime.fromtimestamp(bars[-1]["ts"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    full_result["date_range"] = f"{start_dt} → {end_dt}"

    # 分周期
    n = len(bars)
    periods = {}
    for days, label in [(7, "7天"), (30, "30天"), (90, "90天"), (180, "180天"), (365, "1年")]:
        start = max(0, n - days * 96)
        sub_bars = bars[start:]
        if len(sub_bars) < 100: continue
        sub_ind = calc_indicators(sub_bars)
        sub_trades, sub_eq = backtest(sub_bars, sub_ind)
        periods[label] = analyze(sub_trades, sub_eq)

    # 周度/月度
    weekly = {}; monthly = {}
    for t in trades:
        w = datetime.fromtimestamp(t["ts"] / 1000, tz=timezone.utc).strftime("%Y-W%W")
        m = datetime.fromtimestamp(t["ts"] / 1000, tz=timezone.utc).strftime("%Y-%m")
        weekly[w] = weekly.get(w, {"pnl": 0, "trades": 0})
        weekly[w]["pnl"] += t["pnl"]; weekly[w]["trades"] += 1
        monthly[m] = monthly.get(m, {"pnl": 0, "trades": 0})
        monthly[m]["pnl"] += t["pnl"]; monthly[m]["trades"] += 1

    weekly_list = [{"week": w, "pnl": round(d["pnl"], 4), "trades": d["trades"]} for w, d in sorted(weekly.items())]
    monthly_list = [{"month": m, "pnl": round(d["pnl"], 4), "trades": d["trades"]} for m, d in sorted(monthly.items())]

    # 保存
    result = {
        "last_update": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "full_period": full_result,
        "periods": periods,
        "weekly_pnl": weekly_list,
        "monthly_pnl": monthly_list
    }
    with open(OUTPUT_PATH, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 回测完成！全历史: {full_result['total_return']:+.2f}% | 胜率: {full_result['win_rate']:.1f}% | 回撤: {full_result['max_drawdown']:.2f}%", flush=True)
    for label, p in periods.items():
        if p:
            print(f"  {label}: {p.get('total_return',0):+.2f}% | 胜率{p.get('win_rate',0):.1f}% | 回撤{p.get('max_drawdown',0):.2f}%", flush=True)

if __name__ == "__main__":
    main()
