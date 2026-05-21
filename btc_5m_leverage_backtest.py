#!/usr/bin/env python3
"""
BTC 5分钟 快速均线回测 — 含手续费 + 5倍杠杆
OKX永续合约: taker 0.05% × 2 = 0.10% 双边手续费
盈亏 = (毛盈亏% - 0.10%) × 5
"""
import json, subprocess, sys, math
from datetime import datetime, timezone, timedelta

def okx_cmd(args):
    cmd = ["okx"] + args
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0: raise RuntimeError(f"okx error: {r.stderr.strip()}")
    return json.loads(r.stdout)

def parse_bar(bar):
    return {"ts": int(bar[0]), "o": float(bar[1]), "h": float(bar[2]),
            "l": float(bar[3]), "c": float(bar[4]),
            "v": float(bar[5]) if len(bar) > 5 else 0,
            "dt": datetime.fromtimestamp(int(bar[0])/1000, tz=timezone.utc)}

# ===== 数据 =====
print("拉取数据...")
daily_raw = okx_cmd(["market", "candles", "BTC-USDT", "--bar", "1D", "--limit", "300", "--json"])
daily = [parse_bar(b) for b in daily_raw]; daily.sort(key=lambda x: x["ts"])
print(f"  日线: {len(daily)}条")

m5_raw = okx_cmd(["market", "candles", "BTC-USDT", "--bar", "5m", "--limit", "300", "--json"])
m5 = [parse_bar(b) for b in m5_raw]; m5.sort(key=lambda x: x["ts"])
print(f"  5m: {len(m5)}条, {m5[0]['dt']}~{m5[-1]['dt']}")

n_daily = len(daily)
dc = [b["c"] for b in daily]
ma730 = sum(dc[-min(730,n_daily):]) / min(730,n_daily)
ma200 = sum(dc[-min(200,n_daily):]) / min(200,n_daily)
print(f"  MA{min(730,n_daily)}: {ma730:.2f} | MA200: {ma200:.2f} | BTC: {m5[-1]['c']:.2f}")
print(f"  趋势: {'多' if m5[-1]['c']>ma730 else '空'}")

# 日线MA匹配
def daily_ma_at(daily_data, period, target_ts):
    td = datetime.fromtimestamp(target_ts/1000, tz=timezone.utc).date()
    cl = []
    for b in reversed(daily_data):
        if datetime.fromtimestamp(b["ts"]/1000, tz=timezone.utc).date() <= td:
            cl.append(b["c"])
    cl.reverse()
    return sum(cl[-period:]) / period if len(cl) >= period else None

# 计算MA5和MA13
m5c = [b["c"] for b in m5]
ma5_vals, ma13_vals, ma5_p, ma13_p = [], [], [], []
for i in range(len(m5c)):
    if i >= 4:
        ma5_vals.append(sum(m5c[i-4:i+1])/5)
        ma5_p.append(sum(m5c[i-5:i])/5 if i>=5 else None)
    else:
        ma5_vals.append(None); ma5_p.append(None)
    if i >= 12:
        ma13_vals.append(sum(m5c[i-12:i+1])/13)
        ma13_p.append(sum(m5c[i-13:i])/13 if i>=13 else None)
    else:
        ma13_vals.append(None); ma13_p.append(None)

ma730_arr = [daily_ma_at(daily, min(730,n_daily), b["ts"]) for b in m5]
ma200_arr = [daily_ma_at(daily, min(200,n_daily), b["ts"]) for b in m5]

# ===== 参数 =====
FEE = 0.10     # 双边手续费 %
LEVERAGE = 5   # 5倍杠杆

# 多组参数：TP必须 > FEE才能盈利
# 净盈亏% = (毛盈亏% - FEE) × LEVERAGE
# 止盈触发 = 毛盈亏 >= TP → 净盈 = (TP - FEE) × LEVERAGE
# 止损触发 = 毛盈亏 <= -SL → 净亏 = (-SL - FEE) × LEVERAGE

param_sets = [
    # 为了覆盖0.10%手续费，TP至少0.20%+ 才有意义
    {"tp": 0.22, "sl": 0.12, "max_bars": 10, "name": "TP0.22/SL0.12(50min)"},
    {"tp": 0.25, "sl": 0.15, "max_bars": 10, "name": "TP0.25/SL0.15(50min)"},
    {"tp": 0.28, "sl": 0.15, "max_bars": 12, "name": "TP0.28/SL0.15(60min)"},
    {"tp": 0.30, "sl": 0.18, "max_bars": 12, "name": "TP0.30/SL0.18(60min)"},
    {"tp": 0.35, "sl": 0.20, "max_bars": 14, "name": "TP0.35/SL0.20(70min)"},
]

# 先跑所有参数
all_results = []
for ps in param_sets:
    TP, SL, MAX_BARS = ps["tp"], ps["sl"], ps["max_bars"]
    trades = []
    position = None
    
    for gi, bar in enumerate(m5):
        c = bar["c"]
        ma7v = ma730_arr[gi]; ma200v = ma200_arr[gi]
        ma5v = ma5_vals[gi]; ma13v = ma13_vals[gi]
        ma5pv = ma5_p[gi]; ma13pv = ma13_p[gi]
        
        if None in (ma7v, ma200v, ma5v, ma13v, ma5pv, ma13pv):
            continue
        
        trend_up = c > ma7v; trend_down = c < ma7v
        near_ma = abs(c - ma7v) / ma7v < 0.005
        strong_up = c > ma200v; strong_down = c < ma200v
        golden = ma5pv <= ma13pv and ma5v > ma13v
        death = ma5pv >= ma13pv and ma5v < ma13v
        
        if position is not None:
            ep = position["price"]; ei = position["idx"]; held = gi - ei
            gross_pnl = (c-ep)/ep*100 if position["type"]=="long" else (ep-c)/ep*100
            
            reason = None
            if gross_pnl >= TP: reason = "止盈"
            elif gross_pnl <= -SL: reason = "止损"
            elif position["type"]=="long" and (trend_down or death): reason = "反"
            elif position["type"]=="short" and (trend_up or golden): reason = "反"
            elif held >= MAX_BARS: reason = "超时"
            
            if reason:
                net_pnl = (gross_pnl - FEE) * LEVERAGE
                trades.append({
                    "dir": position["type"],
                    "in": m5[ei]["dt"].strftime("%m-%d %H:%M"),
                    "out": bar["dt"].strftime("%m-%d %H:%M"),
                    "entry": ep, "exit": c,
                    "gross": round(gross_pnl, 4),
                    "net": round(net_pnl, 4),
                    "bars": held, "mins": held*5, "reason": reason
                })
                position = None
            continue
        
        if near_ma: continue
        
        if trend_up and strong_up and golden:
            position = {"type": "long", "idx": gi, "price": c}
        elif trend_down and strong_down and death:
            position = {"type": "short", "idx": gi, "price": c}
    
    if position:
        lb = m5[-1]; c = lb["c"]; ep = position["price"]
        gross_pnl = (c-ep)/ep*100 if position["type"]=="long" else (ep-c)/ep*100
        held = len(m5)-1-position["idx"]
        net_pnl = (gross_pnl - FEE) * LEVERAGE
        trades.append({
            "dir": position["type"],
            "in": m5[position["idx"]]["dt"].strftime("%m-%d %H:%M"),
            "out": lb["dt"].strftime("%m-%d %H:%M"),
            "entry": ep, "exit": c,
            "gross": round(gross_pnl, 4),
            "net": round(net_pnl, 4),
            "bars": held, "mins": held*5, "reason": "结束"
        })
    
    wins = sum(1 for t in trades if t["net"] > 0)
    total_net = sum(t["net"] for t in trades)
    total_gross = sum(t["gross"] for t in trades)
    avg_net = total_net/len(trades) if trades else 0
    wr = wins/len(trades)*100 if trades else 0
    
    # 用$37.54本金算美元收益
    usd_profit = total_net / 100 * 37.54
    
    all_results.append({
        **ps,
        "trades": len(trades), "wins": wins, "wr": wr,
        "total_gross": total_gross, "total_net": total_net,
        "total_fee": len(trades) * FEE,
        "avg_net": avg_net, "usd_profit": usd_profit,
        "detail": trades
    })

# ===== 输出 =====
print(f"\n{'='*100}")
print(f"BTC 5分钟 MA5/MA13  含手续费({FEE}%) + {LEVERAGE}x杠杆  本金$37.54")
print(f"{'='*100}")
print(f"MA{min(730,n_daily)}(2年): {ma730:.2f} | MA200: {ma200:.2f} | 趋势: {'多头' if m5[-1]['c']>ma730 else '空头'}")
print(f"数据: {len(m5)}根5min, {m5[0]['dt'].strftime('%m-%d %H:%M')}~{m5[-1]['dt'].strftime('%m-%d %H:%M')} (约25h)")
print()
print(f"{'参数':<22} {'笔数':>4} {'胜率':>7} {'毛盈亏%':>9} {'手续费%':>8} {'净盈亏%':>9} {'$收益':>8}")
print(f"{'─'*70}")

best = None
for r in all_results:
    wr_fmt = f"{r['wins']}/{r['trades']}={r['wr']:.0f}%" if r['trades'] else "N/A"
    print(f"{r['name']:<22} {r['trades']:>4} {wr_fmt:>7} {r['total_gross']:>+9.2f} {r['total_fee']:>+8.2f} {r['total_net']:>+9.2f} {r['usd_profit']:>+8.2f}")
    if best is None or r['total_net'] > best['total_net']:
        best = r

# ===== 最佳方案详情 =====
print(f"\n{'='*100}")
print(f"🏆 最佳方案: {best['name']}")
print(f"{'='*100}")
print(f"毛盈亏: {best['total_gross']:+.2f}% | 手续费: -{best['total_fee']:.2f}% | 净盈亏: {best['total_net']:+.2f}%")
print(f"$收益: {best['usd_profit']:+.2f} | 胜率: {best['wins']}/{best['trades']}={best['wr']:.0f}%")
print()

print(f"{'方向':^6} {'入场':^12} {'出场':^12} {'入场价':>9} {'出场价':>9} {'毛盈亏%':>8} {'手续费%':>8} {'净盈亏%':>9} {'持仓':>6} {'原因':^6}")
print(f"{'─'*100}")

for t in best['detail']:
    d = "多🔴" if t["dir"]=="long" else "空🟢"
    g = f"{t['gross']:+6.2f}%"
    n = f"{t['net']:+7.2f}%"
    print(f"{d:^6} {t['in']:^12} {t['out']:^12} {t['entry']:>9.1f} {t['exit']:>9.1f} {g:>8}   -0.10%  {n:>9} {t['mins']:>4}min {t['reason']:^6}")

print(f"{'─'*100}")

# 盈亏比
win_t = [t for t in best['detail'] if t['net'] > 0]
loss_t = [t for t in best['detail'] if t['net'] <= 0]
if win_t and loss_t:
    aw = sum(t['net'] for t in win_t) / len(win_t)
    al = abs(sum(t['net'] for t in loss_t) / len(loss_t))
    print(f"\n📊 平均盈利: +{aw:.2f}% | 平均亏损: -{al:.2f}% | 盈亏比: {aw/al:.2f}")

if len(best['detail']) > 1:
    pnls = [t['net'] for t in best['detail']]
    a = sum(pnls)/len(pnls)
    s = math.sqrt(sum((x-a)**2 for x in pnls)/len(pnls))
    sharpe = a/s*math.sqrt(len(pnls)) if s>0 else 0
    print(f"📐 夏普比率: {sharpe:.2f}")

# ===== 所有方案对比摘要 =====
print(f"\n{'='*100}")
print("📊 各方案汇总")
print(f"{'='*100}")
print(f"{'方案':<28} {'净盈亏%':>9} {'$收益':>8} {'胜率':>7} {'交易':>4}")
print(f"{'─'*60}")
for r in all_results:
    wr_str = f"{r['wins']}/{r['trades']}={r['wr']:.0f}%" if r['trades'] else "N/A"
    print(f"{r['name']:<28} {r['total_net']:>+9.2f} {r['usd_profit']:>+8.2f} {wr_str:>7} {r['trades']:>4}")

print(f"\n⚠️ 数据仅25小时(300根5min)，5倍杠杆放大收益和亏损。手续费0.10%双边是硬成本。")
print(f"{'='*100}")
