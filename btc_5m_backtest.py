#!/usr/bin/env python3
"""
BTC 5分钟 三层均线回测
MA730(2年日线)定方向 + MA200(日线)过滤 + MA9/MA21金死叉入场(5分钟)
"""
import json, subprocess, sys, math
from datetime import datetime, timezone, timedelta

def okx_cmd(args):
    cmd = ["okx"] + args
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"okx error: {r.stderr.strip()}")
    return json.loads(r.stdout)

def parse_bar(bar):
    return {
        "ts": int(bar[0]),
        "o": float(bar[1]), "h": float(bar[2]), "l": float(bar[3]),
        "c": float(bar[4]), "v": float(bar[5]) if len(bar) > 5 else 0,
        "dt": datetime.fromtimestamp(int(bar[0])/1000, tz=timezone.utc)
    }

# ===== 拉取数据 =====
print("拉取日线数据 (长周期MA)...")
daily_raw = okx_cmd(["market", "candles", "BTC-USDT", "--bar", "1D", "--limit", "300", "--json"])
daily = [parse_bar(b) for b in daily_raw]
daily.sort(key=lambda x: x["ts"])
print(f"  日线: {len(daily)} 条, {daily[0]['dt'].date()} ~ {daily[-1]['dt'].date()}")

print("拉取5分钟K线...")
m5_raw = okx_cmd(["market", "candles", "BTC-USDT", "--bar", "5m", "--limit", "300", "--json"])
m5 = [parse_bar(b) for b in m5_raw]
m5.sort(key=lambda x: x["ts"])
print(f"  5m: {len(m5)} 条, {m5[0]['dt']} ~ {m5[-1]['dt']}")

# 拉取更多5分钟数据（需要覆盖7天 ≈ 2016根）
# 300根只覆盖约1天，需要多次拉取
# 用不同策略：先拉300根最新，再拉历史
print("  继续拉取历史5分钟数据...")
# OKX API 的 candles 可能支持 after/before 参数，试一下
# 先尝试直接拉更多
all_m5 = list(m5)
# 尝试用不同方式拉取更多数据
for attempt in range(6):
    oldest_ts = all_m5[-1]["ts"]  # 最早的时间戳(因为是倒序)
    # 尝试 before 参数
    try:
        more = okx_cmd(["market", "candles", "BTC-USDT", "--bar", "5m", "--limit", "300", "--json"])
        more_bars = [parse_bar(b) for b in more]
        # 过滤已有数据
        existing_ts = {b["ts"] for b in all_m5}
        new_bars = [b for b in more_bars if b["ts"] not in existing_ts]
        if not new_bars:
            break
        all_m5.extend(new_bars)
        print(f"    +{len(new_bars)} 条, 总计 {len(all_m5)}")
    except:
        break

all_m5.sort(key=lambda x: x["ts"])
print(f"  5分钟总计: {len(all_m5)} 条, {all_m5[0]['dt']} ~ {all_m5[-1]['dt']}")

# 计算日线MA
daily_closes = [b["c"] for b in daily]
n_daily = len(daily_closes)

def sma(arr, n):
    if len(arr) < n: return None
    return sum(arr[-n:]) / n

ma730_daily = sma(daily_closes, min(730, n_daily))
ma200_daily = sma(daily_closes, min(200, n_daily))
print(f"  日线MA{min(730,n_daily)}(≈2年线): {ma730_daily:.2f}")
print(f"  日线MA200: {ma200_daily:.2f}")

# 匹配日线MA到5分钟
def daily_ma_at(daily_data, period, target_ts):
    target_dt = datetime.fromtimestamp(target_ts/1000, tz=timezone.utc)
    target_date = target_dt.date()
    closes_list = []
    for b in reversed(daily_data):
        b_date = datetime.fromtimestamp(b["ts"]/1000, tz=timezone.utc).date()
        if b_date <= target_date:
            closes_list.append(b["c"])
    closes_list.reverse()
    if len(closes_list) >= period:
        return sum(closes_list[-period:]) / period
    return None

m5_closes = [b["c"] for b in all_m5]

# 5分钟级别滚动 MA9 和 MA21
ma9_vals, ma21_vals = [], []
ma9_prev_vals, ma21_prev_vals = [], []

for i in range(len(m5_closes)):
    if i >= 8:
        ma9_vals.append(sum(m5_closes[i-8:i+1]) / 9)
        ma9_prev_vals.append(sum(m5_closes[i-9:i]) / 9 if i >= 9 else None)
    else:
        ma9_vals.append(None); ma9_prev_vals.append(None)
    
    if i >= 20:
        ma21_vals.append(sum(m5_closes[i-20:i+1]) / 21)
        ma21_prev_vals.append(sum(m5_closes[i-21:i]) / 21 if i >= 21 else None)
    else:
        ma21_vals.append(None); ma21_prev_vals.append(None)

# 匹配日线MA
ma730_arr = [daily_ma_at(daily, min(730, n_daily), b["ts"]) for b in all_m5]
ma200_arr = [daily_ma_at(daily, min(200, n_daily), b["ts"]) for b in all_m5]

# ===== 回测参数 =====
TP_PCT = 0.003   # 止盈 0.3%
SL_PCT = 0.002   # 止损 0.2%
MAX_BARS = 24    # 2小时 = 24根5分钟K线

# 回测区间
now = datetime.now(timezone.utc)
seven_days_ago = now - timedelta(days=7)
cutoff_ts = int(seven_days_ago.timestamp() * 1000)

bt_bars = [(i, b) for i, b in enumerate(all_m5) if b["ts"] >= cutoff_ts]
print(f"\n回测区间: {seven_days_ago.strftime('%Y-%m-%d %H:%M')} ~ {now.strftime('%Y-%m-%d %H:%M')} UTC")
print(f"5分钟K线: {len(bt_bars)} 根")
print(f"止盈: {TP_PCT*100:.1f}% | 止损: {SL_PCT*100:.1f}% | 最大持仓: {MAX_BARS*5}分钟")

# ===== 回测 =====
trades = []
position = None

for idx_in_bt, bar in bt_bars:
    gi = idx_in_bt
    c = bar["c"]
    ma730 = ma730_arr[gi]
    ma200 = ma200_arr[gi]
    ma9 = ma9_vals[gi]
    ma21 = ma21_vals[gi]
    ma9p = ma9_prev_vals[gi]
    ma21p = ma21_prev_vals[gi]
    
    if None in (ma730, ma200, ma9, ma21, ma9p, ma21p):
        continue
    
    trend_up = c > ma730
    trend_down = c < ma730
    near_ma = abs(c - ma730) / ma730 < 0.005  # ±0.5%缠绕区（比15分钟更窄）
    
    strong_up = c > ma200
    strong_down = c < ma200
    
    golden = ma9p <= ma21p and ma9 > ma21
    death = ma9p >= ma21p and ma9 < ma21
    
    # 持仓管理
    if position is not None:
        ep = position["price"]
        ei = position["idx"]
        held = gi - ei
        pnl = (c - ep) / ep * 100 if position["type"] == "long" else (ep - c) / ep * 100
        
        exit_reason = None
        
        if pnl >= TP_PCT * 100:
            exit_reason = "止盈"
        elif pnl <= -SL_PCT * 100:
            exit_reason = "止损"
        elif position["type"] == "long" and (trend_down or death):
            exit_reason = "反转/破位"
        elif position["type"] == "short" and (trend_up or golden):
            exit_reason = "反转/破位"
        elif held >= MAX_BARS:
            exit_reason = "超时"
        
        if exit_reason:
            trades.append({
                "dir": position["type"], "in": all_m5[ei]["dt"].strftime("%m-%d %H:%M"),
                "out": bar["dt"].strftime("%m-%d %H:%M"),
                "entry": ep, "exit": c, "pnl": round(pnl, 4),
                "bars": held, "mins": held * 5, "reason": exit_reason
            })
            position = None
        continue
    
    # 入场
    if near_ma:
        continue
    
    if trend_up and strong_up and golden:
        position = {"type": "long", "idx": gi, "price": c}
    elif trend_down and strong_down and death:
        position = {"type": "short", "idx": gi, "price": c}

# 强制平仓
if position:
    lb = all_m5[-1]; c = lb["c"]; ep = position["price"]
    pnl = (c - ep) / ep * 100 if position["type"] == "long" else (ep - c) / ep * 100
    held = len(all_m5) - 1 - position["idx"]
    trades.append({
        "dir": position["type"], "in": all_m5[position["idx"]]["dt"].strftime("%m-%d %H:%M"),
        "out": lb["dt"].strftime("%m-%d %H:%M"),
        "entry": ep, "exit": c, "pnl": round(pnl, 4),
        "bars": held, "mins": held * 5, "reason": "回测结束"
    })

# ===== 输出 =====
print(f"\n{'='*90}")
print(f"BTC 5分钟 三层均线回测结果")
print(f"{'='*90}")
print(f"当前BTC: {all_m5[-1]['c']:.2f} | MA730(2年线): {ma730_daily:.2f} | MA200: {ma200_daily:.2f}")
trend_now = "多头" if all_m5[-1]['c'] > ma730_daily else "空头"
print(f"当前趋势: {trend_now} | 止盈{TP_PCT*100:.1f}% | 止损{SL_PCT*100:.1f}% | 最大{MAX_BARS*5}分钟")

if not trades:
    print(f"\n⚠️ 回测期间无交易信号 ({len(bt_bars)}根K线)")
    sys.exit(0)

print(f"\n📊 总交易: {len(trades)} 笔")
print(f"{'─'*95}")
print(f"{'方向':^6} {'入场':^12} {'出场':^12} {'入场价':>10} {'出场价':>10} {'盈亏%':>9} {'持仓':>8} {'原因':^12}")
print(f"{'─'*95}")

for t in trades:
    d = "多🔴" if t["dir"] == "long" else "空🟢"
    p = f"+{t['pnl']:.2f}%" if t['pnl'] >= 0 else f"{t['pnl']:.2f}%"
    print(f"{d:^6} {t['in']:^12} {t['out']:^12} {t['entry']:>10.2f} {t['exit']:>10.2f} {p:>9} {t['mins']:>4}分钟 {t['reason']:^12}")

print(f"{'─'*95}")

wins = sum(1 for t in trades if t["pnl"] > 0)
total_pnl = sum(t["pnl"] for t in trades)
avg_pnl = total_pnl / len(trades) if trades else 0

print(f"\n✅ 胜率: {wins}/{len(trades)} = {wins/len(trades)*100:.1f}%")
print(f"💰 累计盈亏: {total_pnl:+.2f}%")
print(f"📈 平均每笔: {avg_pnl:+.4f}%")
print(f"⏱️ 日均交易: {len(trades)/7:.1f} 笔")

lts = [t for t in trades if t["dir"] == "long"]
sts = [t for t in trades if t["dir"] == "short"]
if lts:
    lw = sum(1 for t in lts if t["pnl"] > 0)
    print(f"\n🔴 多头: {len(lts)}笔 | 胜率 {lw}/{len(lts)}={lw/len(lts)*100:.1f}% | 盈亏 {sum(t['pnl'] for t in lts):+.2f}%")
if sts:
    sw = sum(1 for t in sts if t["pnl"] > 0)
    print(f"🟢 空头: {len(sts)}笔 | 胜率 {sw}/{len(sts)}={sw/len(sts)*100:.1f}% | 盈亏 {sum(t['pnl'] for t in sts):+.2f}%")

print("\n按平仓原因:")
reasons = {}
for t in trades:
    r = t["reason"]
    if r not in reasons: reasons[r] = {"n": 0, "pnl": 0, "w": 0}
    reasons[r]["n"] += 1; reasons[r]["pnl"] += t["pnl"]
    if t["pnl"] > 0: reasons[r]["w"] += 1
for r, s in sorted(reasons.items(), key=lambda x: -x[1]["n"]):
    print(f"  {r}: {s['n']}笔 (胜{s['w']}/{s['n']}), 盈亏 {s['pnl']:+.2f}%")

print("\n按天:")
days = {}
for t in trades:
    d = t["in"][:5]
    if d not in days: days[d] = {"n": 0, "w": 0, "pnl": 0}
    days[d]["n"] += 1; days[d]["pnl"] += t["pnl"]
    if t["pnl"] > 0: days[d]["w"] += 1
for d in sorted(days):
    s = days[d]
    print(f"  {d}: {s['n']}笔, 胜{s['w']}/{s['n']}, 盈亏 {s['pnl']:+.2f}%")

if len(trades) > 1:
    pnls = [t["pnl"] for t in trades]
    avg = sum(pnls) / len(pnls)
    std = math.sqrt(sum((x - avg)**2 for x in pnls) / len(pnls))
    sharpe = avg / std * math.sqrt(len(trades)) if std > 0 else 0
    print(f"\n📐 夏普比率: {sharpe:.2f}")

# 盈亏比
win_trades = [t for t in trades if t["pnl"] > 0]
loss_trades = [t for t in trades if t["pnl"] <= 0]
if win_trades and loss_trades:
    avg_win = sum(t["pnl"] for t in win_trades) / len(win_trades)
    avg_loss = abs(sum(t["pnl"] for t in loss_trades) / len(loss_trades))
    print(f"📊 盈亏比: {avg_win:.2f}% / {avg_loss:.2f}% = {avg_win/avg_loss:.2f}" if avg_loss > 0 else f"📊 平均盈利: {avg_win:.2f}%")

print(f"\n{'='*90}")
