#!/usr/bin/env python3
"""
BTC 15分钟 三层均线回测
MA70080(2年线)定方向 + MA14400(200日)过滤 + MA9/MA21金死叉入场
"""
import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta

def okx_cmd(args):
    """调用okx CLI"""
    cmd = ["okx"] + args
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"okx error: {r.stderr.strip()}")
    return json.loads(r.stdout)

def parse_bar(bar):
    """解析K线 [ts, o, h, l, c, vol, ...]"""
    return {
        "ts": int(bar[0]),
        "o": float(bar[1]), "h": float(bar[2]), "l": float(bar[3]),
        "c": float(bar[4]), "v": float(bar[5]) if len(bar) > 5 else 0,
        "dt": datetime.fromtimestamp(int(bar[0])/1000, tz=timezone.utc)
    }

# ===== 拉取数据 =====
print("拉取日线数据 (用于长周期MA)...")
daily_raw = okx_cmd(["market", "candles", "BTC-USDT", "--bar", "1D", "--limit", "300", "--json"])
daily = [parse_bar(b) for b in daily_raw]
daily.sort(key=lambda x: x["ts"])
print(f"  日线: {len(daily)} 条, {daily[0]['dt'].date()} ~ {daily[-1]['dt'].date()}")

print("拉取15分钟K线...")
m15_raw = okx_cmd(["market", "candles", "BTC-USDT", "--bar", "15m", "--limit", "300", "--json"])
m15 = [parse_bar(b) for b in m15_raw]
m15.sort(key=lambda x: x["ts"])
print(f"  15m: {len(m15)} 条, {m15[0]['dt']} ~ {m15[-1]['dt']}")

# 计算日线MA
daily_closes = [b["c"] for b in daily]

def sma(arr, n):
    if len(arr) < n: return None
    return sum(arr[-n:]) / n

ma730_daily = sma(daily_closes, min(730, len(daily_closes)))
ma200_daily = sma(daily_closes, min(200, len(daily_closes)))
print(f"  日线MA{min(730,len(daily_closes))} (≈2年线): {ma730_daily:.2f}")
print(f"  日线MA200: {ma200_daily:.2f}")

# 对每根15分钟K线，匹配对应日期的日线MA值（取 <= 该时间的最新日线MA）
def daily_ma_at(daily_data, period, target_ts):
    """返回target_ts时对应的period日线MA值"""
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

# 为每根15min K线计算MA值
m15_closes = [b["c"] for b in m15]

# 滚动计算MA9和MA21
ma9_vals = []
ma21_vals = []
ma9_prev_vals = []
ma21_prev_vals = []

for i in range(len(m15_closes)):
    if i >= 8:
        ma9_vals.append(sum(m15_closes[i-8:i+1]) / 9)
        ma9_prev_vals.append(sum(m15_closes[i-9:i]) / 9 if i >= 9 else None)
    else:
        ma9_vals.append(None)
        ma9_prev_vals.append(None)
    
    if i >= 20:
        ma21_vals.append(sum(m15_closes[i-20:i+1]) / 21)
        ma21_prev_vals.append(sum(m15_closes[i-21:i]) / 21 if i >= 21 else None)
    else:
        ma21_vals.append(None)
        ma21_prev_vals.append(None)

# 匹配日线MA到15分钟
ma730_at_bar = []
ma200_at_bar = []
for b in m15:
    ma730_at_bar.append(daily_ma_at(daily, 730, b["ts"]) if len(daily) >= 730 else daily_ma_at(daily, len(daily), b["ts"]))
    ma200_at_bar.append(daily_ma_at(daily, 200, b["ts"]) if len(daily) >= 200 else daily_ma_at(daily, len(daily), b["ts"]))

# ===== 回测(最近7天) =====
now = datetime.now(timezone.utc)
seven_days_ago = now - timedelta(days=7)
cutoff_ts = int(seven_days_ago.timestamp() * 1000)

bt_bars = [(i, b) for i, b in enumerate(m15) if b["ts"] >= cutoff_ts]
print(f"\n回测区间: {seven_days_ago.strftime('%Y-%m-%d %H:%M')} ~ {now.strftime('%Y-%m-%d %H:%M')} UTC")
print(f"K线数: {len(bt_bars)}")

# 回测参数
TP_PCT = 0.008   # 止盈 0.8%
SL_PCT = 0.005   # 止损 0.5%
MAX_BARS = 12    # 最大持仓12根K线(3小时)

trades = []
position = None  # {"type": "long"/"short", "idx": global_idx, "price": entry_price}

for idx_in_bt, bar in bt_bars:
    gi = idx_in_bt  # global index in m15
    c = bar["c"]
    ma730 = ma730_at_bar[gi]
    ma200 = ma200_at_bar[gi]
    ma9 = ma9_vals[gi]
    ma21 = ma21_vals[gi]
    ma9p = ma9_prev_vals[gi]
    ma21p = ma21_prev_vals[gi]
    
    if None in (ma730, ma200, ma9, ma21, ma9p, ma21p):
        continue
    
    # 趋势判断
    trend_up = c > ma730
    trend_down = c < ma730
    near_ma = abs(c - ma730) / ma730 < 0.008  # ±0.8% = 缠绕区
    
    # 强度过滤
    strong_up = c > ma200
    strong_down = c < ma200
    
    # 交叉
    golden = ma9p <= ma21p and ma9 > ma21
    death = ma9p >= ma21p and ma9 < ma21
    
    # === 持仓管理 ===
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
        elif position["type"] == "long" and trend_down and death:
            exit_reason = "趋势反转"
        elif position["type"] == "short" and trend_up and golden:
            exit_reason = "趋势反转"
        elif held >= MAX_BARS:
            exit_reason = "超时"
        
        if exit_reason:
            trades.append({
                "dir": position["type"],
                "in": m15[ei]["dt"].strftime("%m-%d %H:%M"),
                "out": bar["dt"].strftime("%m-%d %H:%M"),
                "entry": ep,
                "exit": c,
                "pnl": round(pnl, 4),
                "bars": held,
                "reason": exit_reason
            })
            position = None
        continue
    
    # === 入场 ===
    if near_ma:
        continue
    
    if trend_up and strong_up and golden:
        position = {"type": "long", "idx": gi, "price": c}
    elif trend_down and strong_down and death:
        position = {"type": "short", "idx": gi, "price": c}

# 未平仓强制平仓
if position:
    lb = m15[-1]
    c = lb["c"]
    ep = position["price"]
    pnl = (c - ep) / ep * 100 if position["type"] == "long" else (ep - c) / ep * 100
    trades.append({
        "dir": position["type"],
        "in": m15[position["idx"]]["dt"].strftime("%m-%d %H:%M"),
        "out": lb["dt"].strftime("%m-%d %H:%M"),
        "entry": ep,
        "exit": c,
        "pnl": round(pnl, 4),
        "bars": len(m15) - 1 - position["idx"],
        "reason": "回测结束"
    })

# ===== 输出 =====
print(f"\n{'='*80}")
print(f"BTC 三层均线回测结果")
print(f"{'='*80}")
print(f"当前BTC: {m15[-1]['c']:.2f} | MA730(2年): {ma730_daily:.2f} | MA200: {ma200_daily:.2f}")
trend_now = "多头" if m15[-1]['c'] > ma730_daily else "空头"
print(f"当前趋势: {trend_now} (vs 2年线)")
print(f"止盈: {TP_PCT*100:.1f}% | 止损: {SL_PCT*100:.1f}% | 最大持仓: {MAX_BARS*15}分钟")

if not trades:
    print("\n⚠️ 回测期间无交易信号")
    sys.exit(0)

print(f"\n📊 总交易: {len(trades)} 笔")
print(f"{'─'*85}")
print(f"{'方向':^6} {'入场':^12} {'出场':^12} {'入场价':>10} {'出场价':>10} {'盈亏%':>9} {'K线':>5} {'原因':^10}")
print(f"{'─'*85}")

for t in trades:
    d = "多" if t["dir"] == "long" else "空"
    p = f"+{t['pnl']:.2f}%" if t['pnl'] >= 0 else f"{t['pnl']:.2f}%"
    print(f"{d:^6} {t['in']:^12} {t['out']:^12} {t['entry']:>10.2f} {t['exit']:>10.2f} {p:>9} {t['bars']:>4}根 {t['reason']:^10}")

print(f"{'─'*85}")

wins = sum(1 for t in trades if t["pnl"] > 0)
total_pnl = sum(t["pnl"] for t in trades)
avg_pnl = total_pnl / len(trades) if trades else 0

print(f"\n✅ 胜率: {wins}/{len(trades)} = {wins/len(trades)*100:.1f}%")
print(f"💰 累计盈亏: {total_pnl:+.2f}%")
print(f"📈 平均每笔: {avg_pnl:+.4f}%")

# 按方向
lts = [t for t in trades if t["dir"] == "long"]
sts = [t for t in trades if t["dir"] == "short"]
if lts:
    lw = sum(1 for t in lts if t["pnl"] > 0)
    print(f"\n🔴 多头: {len(lts)}笔 | 胜率 {lw}/{len(lts)}={lw/len(lts)*100:.1f}% | 盈亏 {sum(t['pnl'] for t in lts):+.2f}%")
if sts:
    sw = sum(1 for t in sts if t["pnl"] > 0)
    print(f"🟢 空头: {len(sts)}笔 | 胜率 {sw}/{len(sts)}={sw/len(sts)*100:.1f}% | 盈亏 {sum(t['pnl'] for t in sts):+.2f}%")

# 按原因
print("\n按平仓原因:")
reasons = {}
for t in trades:
    r = t["reason"]
    if r not in reasons: reasons[r] = {"n": 0, "pnl": 0}
    reasons[r]["n"] += 1
    reasons[r]["pnl"] += t["pnl"]
for r, s in sorted(reasons.items(), key=lambda x: -x[1]["n"]):
    print(f"  {r}: {s['n']}笔, 盈亏 {s['pnl']:+.2f}%")

# 按天
print("\n按天:")
days = {}
for t in trades:
    d = t["in"][:5]
    if d not in days: days[d] = {"n": 0, "w": 0, "pnl": 0}
    days[d]["n"] += 1
    days[d]["pnl"] += t["pnl"]
    if t["pnl"] > 0: days[d]["w"] += 1
for d in sorted(days):
    s = days[d]
    print(f"  {d}: {s['n']}笔, 胜{s['w']}/{s['n']}, 盈亏 {s['pnl']:+.2f}%")

# 夏普近似
import math
if len(trades) > 1:
    pnls = [t["pnl"] for t in trades]
    avg = sum(pnls) / len(pnls)
    std = math.sqrt(sum((x - avg)**2 for x in pnls) / len(pnls))
    sharpe = avg / std * math.sqrt(len(trades)) if std > 0 else 0
    print(f"\n📐 夏普比率(近似): {sharpe:.2f}")

print(f"\n{'='*80}")
