#!/usr/bin/env python3
"""
BTC 15分钟 三层均线+波动率过滤+maker入场+大止盈
改进1: ATR波动率过滤，震荡市休息
改进2: 入场用limit(maker 0.02%)，出场用market(taker 0.05%)，双边0.07%
改进3: 15分钟级别，大止盈覆盖手续费
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

# ===== 拉数据 =====
print("拉取数据...")
daily_raw = okx_cmd(["market", "candles", "BTC-USDT", "--bar", "1D", "--limit", "300", "--json"])
daily = [parse_bar(b) for b in daily_raw]; daily.sort(key=lambda x: x["ts"])
print(f"  日线: {len(daily)}条, {daily[0]['dt'].date()}~{daily[-1]['dt'].date()}")

m15_raw = okx_cmd(["market", "candles", "BTC-USDT", "--bar", "15m", "--limit", "300", "--json"])
m15 = [parse_bar(b) for b in m15_raw]; m15.sort(key=lambda x: x["ts"])
print(f"  15m: {len(m15)}条, {m15[0]['dt']}~{m15[-1]['dt']}")

n_daily = len(daily); dc = [b["c"] for b in daily]
ma730 = sum(dc[-min(730,n_daily):]) / min(730,n_daily)
ma200 = sum(dc[-min(200,n_daily):]) / min(200,n_daily)
print(f"  MA{min(730,n_daily)}: {ma730:.2f} | MA200: {ma200:.2f} | BTC: {m15[-1]['c']:.2f}")

def daily_ma_at(daily_data, period, target_ts):
    td = datetime.fromtimestamp(target_ts/1000, tz=timezone.utc).date()
    cl = []
    for b in reversed(daily_data):
        if datetime.fromtimestamp(b["ts"]/1000, tz=timezone.utc).date() <= td:
            cl.append(b["c"])
    cl.reverse()
    return sum(cl[-period:]) / period if len(cl) >= period else None

# ===== 计算指标 =====
closes = [b["c"] for b in m15]
highs = [b["h"] for b in m15]
lows = [b["l"] for b in m15]

# MA9, MA21
ma9_v, ma21_v, ma9_p, ma21_p = [], [], [], []
for i in range(len(closes)):
    if i >= 8:
        ma9_v.append(sum(closes[i-8:i+1])/9)
        ma9_p.append(sum(closes[i-9:i])/9 if i>=9 else None)
    else:
        ma9_v.append(None); ma9_p.append(None)
    if i >= 20:
        ma21_v.append(sum(closes[i-20:i+1])/21)
        ma21_p.append(sum(closes[i-21:i])/21 if i>=21 else None)
    else:
        ma21_v.append(None); ma21_p.append(None)

# ATR(14) 和 ATR均值用于波动率过滤
tr_vals = []
for i in range(len(closes)):
    if i == 0:
        tr = highs[i] - lows[i]
    else:
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
    tr_vals.append(tr)

atr14 = []
atr14_pct = []  # ATR as % of price
for i in range(len(tr_vals)):
    if i >= 13:
        atr = sum(tr_vals[i-13:i+1]) / 14
        atr14.append(atr)
        atr14_pct.append(atr / closes[i] * 100)
    else:
        atr14.append(None)
        atr14_pct.append(None)

# ATR均值(20)用于比较当前波动率
atr_mean20 = []
for i in range(len(atr14_pct)):
    if i >= 19 and atr14_pct[i] is not None:
        valid = [v for v in atr14_pct[i-19:i+1] if v is not None]
        atr_mean20.append(sum(valid)/len(valid) if valid else None)
    else:
        atr_mean20.append(None)

# 日线MA映射
ma730_arr = [daily_ma_at(daily, min(730,n_daily), b["ts"]) for b in m15]
ma200_arr = [daily_ma_at(daily, min(200,n_daily), b["ts"]) for b in m15]

# ===== 回测参数 =====
FEE_ENTRY = 0.02   # maker入场
FEE_EXIT = 0.05    # taker出场
FEE_TOTAL = FEE_ENTRY + FEE_EXIT  # 0.07%
LEVERAGE = 5

# 波动率过滤阈值
VOL_FILTER_RATIO = 0.7  # 当前ATR < 均值70% = 低波动，不交易
NEAR_MA_THRESHOLD = 0.01  # 价格在MA730 ±1%内 = 缠绕区

param_sets = [
    # TP%, SL%, MAX_BARS(15m), vol_filter, name
    {"tp": 0.50, "sl": 0.30, "max_bars": 12, "vol_f": True,  "name": "TP0.50/SL0.30 波动过滤"},
    {"tp": 0.40, "sl": 0.25, "max_bars": 10, "vol_f": True,  "name": "TP0.40/SL0.25 波动过滤"},
    {"tp": 0.60, "sl": 0.35, "max_bars": 14, "vol_f": True,  "name": "TP0.60/SL0.35 波动过滤"},
    {"tp": 0.50, "sl": 0.30, "max_bars": 12, "vol_f": False, "name": "TP0.50/SL0.30 无过滤"},
    {"tp": 0.40, "sl": 0.25, "max_bars": 10, "vol_f": False, "name": "TP0.40/SL0.25 无过滤"},
]

all_results = []
for ps in param_sets:
    TP, SL, MAX_BARS, USE_VOL_FILTER = ps["tp"], ps["sl"], ps["max_bars"], ps["vol_f"]
    trades = []
    position = None
    skipped_vol = 0
    skipped_ma = 0
    
    for gi, bar in enumerate(m15):
        c = bar["c"]
        ma7v = ma730_arr[gi]; ma200v = ma200_arr[gi]
        ma9 = ma9_v[gi]; ma21 = ma21_v[gi]
        ma9prev = ma9_p[gi]; ma21prev = ma21_p[gi]
        atr_pct = atr14_pct[gi] if gi < len(atr14_pct) else None
        atr_m = atr_mean20[gi] if gi < len(atr_mean20) else None
        
        if None in (ma7v, ma200v, ma9, ma21, ma9prev, ma21prev, atr_pct, atr_m):
            continue
        
        trend_up = c > ma7v; trend_down = c < ma7v
        near_ma = abs(c - ma7v) / ma7v < NEAR_MA_THRESHOLD
        strong_up = c > ma200v; strong_down = c < ma200v
        golden = ma9prev <= ma21prev and ma9 > ma21
        death = ma9prev >= ma21prev and ma9 < ma21
        
        # 波动率过滤：当前ATR过低 = 震荡市，不交易
        low_vol = USE_VOL_FILTER and atr_pct < atr_m * VOL_FILTER_RATIO
        if low_vol and position is None:
            skipped_vol += 1
        
        # === 持仓管理 ===
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
                net_pnl = (gross_pnl - FEE_TOTAL) * LEVERAGE
                trades.append({
                    "dir": position["type"],
                    "in": m15[ei]["dt"].strftime("%m-%d %H:%M"),
                    "out": bar["dt"].strftime("%m-%d %H:%M"),
                    "ep": ep, "exit": c, "gross": round(gross_pnl,4),
                    "net": round(net_pnl,4), "bars": held, "reason": reason
                })
                position = None
            continue
        
        # === 入场 ===
        if near_ma:
            skipped_ma += 1
            continue
        if low_vol:
            continue
        
        if trend_up and strong_up and golden:
            position = {"type": "long", "idx": gi, "price": c}
        elif trend_down and strong_down and death:
            position = {"type": "short", "idx": gi, "price": c}
    
    # 强制平仓
    if position:
        lb = m15[-1]; c = lb["c"]; ep = position["price"]
        gross_pnl = (c-ep)/ep*100 if position["type"]=="long" else (ep-c)/ep*100
        held = len(m15)-1-position["idx"]
        net_pnl = (gross_pnl - FEE_TOTAL) * LEVERAGE
        trades.append({
            "dir": position["type"],
            "in": m15[position["idx"]]["dt"].strftime("%m-%d %H:%M"),
            "out": lb["dt"].strftime("%m-%d %H:%M"),
            "ep": ep, "exit": c, "gross": round(gross_pnl,4),
            "net": round(net_pnl,4), "bars": held, "reason": "结束"
        })
    
    wins = sum(1 for t in trades if t["net"] > 0)
    total_net = sum(t["net"] for t in trades)
    total_gross = sum(t["gross"] for t in trades)
    total_fees = len(trades) * FEE_TOTAL
    usd = total_net / 100 * 37.54
    wr = wins/len(trades)*100 if trades else 0
    
    all_results.append({**ps, "trades": len(trades), "wins": wins, "wr": wr,
                        "total_gross": total_gross, "total_net": total_net,
                        "total_fees": total_fees, "usd": usd,
                        "skip_v": skipped_vol, "skip_m": skipped_ma,
                        "detail": trades})

# ===== 输出 =====
print(f"\n{'='*105}")
print(f"BTC 15分钟 MA9/MA21 | maker入场({FEE_ENTRY}%)+taker出场({FEE_EXIT}%)={FEE_TOTAL}%双边 | {LEVERAGE}x杠杆 | $37.54")
print(f"波动率过滤: ATR<均值{VOL_FILTER_RATIO*100:.0f}%跳过 | MA730缠绕±{NEAR_MA_THRESHOLD*100:.0f}%跳过")
print(f"{'='*105}")
print(f"BTC: {m15[-1]['c']:.2f} | MA730: {ma730:.2f} | 趋势: {'多' if m15[-1]['c']>ma730 else '空'}")
print(f"数据: {len(m15)}根15min, {m15[0]['dt'].strftime('%m-%d %H:%M')}~{m15[-1]['dt'].strftime('%m-%d %H:%M')}")

print(f"\n{'方案':<30} {'笔数':>4} {'胜率':>7} {'毛盈亏%':>9} {'手续费%':>8} {'净盈亏%':>9} {'$收益':>8} {'跳过(波/MA)':>12}")
print(f"{'─'*95}")

best = None
for r in all_results:
    wr_s = f"{r['wins']}/{r['trades']}={r['wr']:.0f}%" if r['trades'] else "0"
    skip_s = f"{r['skip_v']}/{r['skip_m']}"
    print(f"{r['name']:<30} {r['trades']:>4} {wr_s:>7} {r['total_gross']:>+9.2f} {r['total_fees']:>+8.3f} {r['total_net']:>+9.2f} {r['usd']:>+8.2f} {skip_s:>12}")
    if best is None or r['total_net'] > best['total_net']:
        best = r

# ===== 最佳方案详情 =====
if best and best['trades']:
    print(f"\n{'='*105}")
    print(f"🏆 最佳: {best['name']} | 净盈亏: {best['total_net']:+.2f}% | ${best['usd']:+.2f}")
    print(f"{'='*105}")
    print(f"{'方向':^6} {'入场':^12} {'出场':^12} {'入场价':>9} {'出场价':>9} {'毛盈亏%':>8} {'净盈亏%':>9} {'K线':>4} {'原因':^6}")
    print(f"{'─'*90}")
    for t in best['detail']:
        d = "多🔴" if t["dir"]=="long" else "空🟢"
        g = f"{t['gross']:+6.2f}%"
        n = f"{t['net']:+7.2f}%"
        print(f"{d:^6} {t['in']:^12} {t['out']:^12} {t['ep']:>9.1f} {t['exit']:>9.1f} {g:>8} {n:>9} {t['bars']:>3}根 {t['reason']:^6}")
    print(f"{'─'*90}")
    
    win_t = [t for t in best['detail'] if t['net'] > 0]
    loss_t = [t for t in best['detail'] if t['net'] <= 0]
    if win_t and loss_t:
        aw = sum(t['net'] for t in win_t) / len(win_t)
        al = abs(sum(t['net'] for t in loss_t) / len(loss_t))
        print(f"平均盈利: +{aw:.2f}% | 平均亏损: -{al:.2f}% | 盈亏比: {aw/al:.2f}")
    
    if len(best['detail']) > 1:
        pnls = [t['net'] for t in best['detail']]
        a = sum(pnls)/len(pnls)
        s = math.sqrt(sum((x-a)**2 for x in pnls)/len(pnls))
        sharpe = a/s*math.sqrt(len(pnls)) if s>0 else 0
        print(f"夏普: {sharpe:.2f}")

    # ATR统计
    avg_atr = sum(v for v in atr14_pct if v is not None) / sum(1 for v in atr14_pct if v is not None)
    print(f"\n📊 平均ATR(14): {avg_atr:.3f}% (波动率参考)")
    print(f"   波动过滤跳过: {best['skip_v']}根K线 / MA缠绕跳过: {best['skip_m']}根K线")

if not best or not best['trades']:
    print("\n⚠️ 波动率过滤太严格，无交易。建议放宽过滤条件。")

print(f"\n{'='*105}")
print("对比: 原始15分钟(无过滤/全taker 0.10%/5x) → -10.46%/$-3.93")
print(f"{'='*105}")
