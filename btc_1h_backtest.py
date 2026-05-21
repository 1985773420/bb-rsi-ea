#!/usr/bin/env python3
"""
BTC 1小时 三层均线+波动率过滤+maker入场+大止盈 — 12.5天回测
MA730(2年日线)定方向 + MA200(日线)过滤 + MA9/MA21金死叉(1H)
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
dc = [b["c"] for b in daily]
ma730 = sum(dc[-min(730,len(dc)):]) / min(730,len(dc))
ma200 = sum(dc[-min(200,len(dc)):]) / min(200,len(dc))
print(f"  日线: {len(daily)}条 | MA{min(730,len(dc))}: {ma730:.2f} | MA200: {ma200:.2f}")

h1_raw = okx_cmd(["market", "candles", "BTC-USDT", "--bar", "1H", "--limit", "300", "--json"])
h1 = [parse_bar(b) for b in h1_raw]; h1.sort(key=lambda x: x["ts"])
print(f"  1H: {len(h1)}条, {h1[0]['dt']} ~ {h1[-1]['dt']}")
days_span = (h1[-1]["dt"] - h1[0]["dt"]).total_seconds() / 86400
print(f"  跨度: {days_span:.1f}天 | BTC: {h1[-1]['c']:.2f} | 趋势: {'多' if h1[-1]['c']>ma730 else '空'}")

def daily_ma_at(daily_data, period, target_ts):
    td = datetime.fromtimestamp(target_ts/1000, tz=timezone.utc).date()
    cl = []
    for b in reversed(daily_data):
        if datetime.fromtimestamp(b["ts"]/1000, tz=timezone.utc).date() <= td:
            cl.append(b["c"])
    cl.reverse()
    return sum(cl[-period:]) / period if len(cl) >= period else None

# ===== 指标计算 =====
closes = [b["c"] for b in h1]
highs = [b["h"] for b in h1]
lows = [b["l"] for b in h1]

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

# ATR(14)
tr_vals = []
for i in range(len(closes)):
    if i == 0: tr = highs[i] - lows[i]
    else: tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
    tr_vals.append(tr)

atr14_pct = []
for i in range(len(tr_vals)):
    if i >= 13:
        atr = sum(tr_vals[i-13:i+1])/14
        atr14_pct.append(atr / closes[i] * 100)
    else:
        atr14_pct.append(None)

atr_mean20 = []
for i in range(len(atr14_pct)):
    if i >= 19 and atr14_pct[i] is not None:
        valid = [v for v in atr14_pct[i-19:i+1] if v is not None]
        atr_mean20.append(sum(valid)/len(valid))
    else:
        atr_mean20.append(None)

ma730_arr = [daily_ma_at(daily, min(730,len(daily)), b["ts"]) for b in h1]
ma200_arr = [daily_ma_at(daily, min(200,len(daily)), b["ts"]) for b in h1]

# ===== 回测 =====
FEE_ENTRY = 0.02; FEE_EXIT = 0.05; FEE_TOTAL = FEE_ENTRY + FEE_EXIT
LEVERAGE = 5
VOL_RATIO = 0.70; NEAR_MA = 0.015  # 1H级别放宽到±1.5%

param_sets = [
    # TP%, SL%, MAX_BARS, vol_f, name
    {"tp": 1.00, "sl": 0.50, "max_bars": 24, "vf": True,  "name": "TP1.0/SL0.5 过滤 24h"},
    {"tp": 0.80, "sl": 0.45, "max_bars": 20, "vf": True,  "name": "TP0.8/SL0.45 过滤 20h"},
    {"tp": 1.20, "sl": 0.60, "max_bars": 28, "vf": True,  "name": "TP1.2/SL0.6 过滤 28h"},
    {"tp": 1.50, "sl": 0.70, "max_bars": 30, "vf": True,  "name": "TP1.5/SL0.7 过滤 30h"},
    {"tp": 1.00, "sl": 0.50, "max_bars": 24, "vf": False, "name": "TP1.0/SL0.5 无过滤"},
    {"tp": 1.50, "sl": 0.70, "max_bars": 30, "vf": False, "name": "TP1.5/SL0.7 无过滤"},
]

all_results = []

for ps in param_sets:
    TP, SL, MAX_BARS, VF = ps["tp"], ps["sl"], ps["max_bars"], ps["vf"]
    trades = []; position = None; skip_v = 0; skip_m = 0
    
    for gi, bar in enumerate(h1):
        c = bar["c"]
        m7 = ma730_arr[gi]; m2 = ma200_arr[gi]
        m9 = ma9_v[gi]; m21 = ma21_v[gi]
        m9p = ma9_p[gi]; m21p = ma21_p[gi]
        atr = atr14_pct[gi]; atrm = atr_mean20[gi]
        
        if None in (m7, m2, m9, m21, m9p, m21p, atr, atrm): continue
        
        tu = c > m7; td = c < m7
        nm = abs(c-m7)/m7 < NEAR_MA
        su = c > m2; sd = c < m2
        gc = m9p <= m21p and m9 > m21
        dc = m9p >= m21p and m9 < m21
        lv = VF and atr < atrm * VOL_RATIO
        
        if position is not None:
            ep = position["price"]; ei = position["idx"]; held = gi - ei
            gp = (c-ep)/ep*100 if position["type"]=="long" else (ep-c)/ep*100
            
            reason = None
            if gp >= TP: reason = "止盈"
            elif gp <= -SL: reason = "止损"
            elif position["type"]=="long" and (td or dc): reason = "反"
            elif position["type"]=="short" and (tu or gc): reason = "反"
            elif held >= MAX_BARS: reason = "超时"
            
            if reason:
                net = (gp - FEE_TOTAL) * LEVERAGE
                trades.append({"dir": position["type"],
                    "in": h1[ei]["dt"].strftime("%m-%d %H:%M"),
                    "out": bar["dt"].strftime("%m-%d %H:%M"),
                    "ep": ep, "exit": c, "gross": round(gp,4), "net": round(net,4),
                    "bars": held, "hrs": held, "reason": reason})
                position = None
            continue
        
        if nm: skip_m += 1; continue
        if lv: skip_v += 1; continue
        
        if tu and su and gc:
            position = {"type": "long", "idx": gi, "price": c}
        elif td and sd and dc:
            position = {"type": "short", "idx": gi, "price": c}
    
    if position:
        lb = h1[-1]; c = lb["c"]; ep = position["price"]
        gp = (c-ep)/ep*100 if position["type"]=="long" else (ep-c)/ep*100
        held = len(h1)-1-position["idx"]
        net = (gp - FEE_TOTAL) * LEVERAGE
        trades.append({"dir": position["type"],
            "in": h1[position["idx"]]["dt"].strftime("%m-%d %H:%M"),
            "out": lb["dt"].strftime("%m-%d %H:%M"),
            "ep": ep, "exit": c, "gross": round(gp,4), "net": round(net,4),
            "bars": held, "hrs": held, "reason": "结束"})
    
    w = sum(1 for t in trades if t["net"] > 0)
    tn = sum(t["net"] for t in trades)
    tg = sum(t["gross"] for t in trades)
    tf = len(trades) * FEE_TOTAL
    usd = tn/100*37.54
    wr = w/len(trades)*100 if trades else 0
    all_results.append({**ps, "n":len(trades), "w":w, "wr":wr, "tg":tg, "tn":tn, "tf":tf, "usd":usd, "sv":skip_v, "sm":skip_m, "detail":trades})

# ===== 输出 =====
print(f"\n{'='*110}")
print(f"BTC 1H MA9/MA21 | maker({FEE_ENTRY}%)+taker({FEE_EXIT}%)={FEE_TOTAL}% | {LEVERAGE}x | $37.54 | 波动过滤ATR<{VOL_RATIO*100:.0f}%")
print(f"{'='*110}")
print(f"{'方案':<28} {'交易':>4} {'胜率':>7} {'毛盈亏%':>9} {'手续费%':>8} {'净盈亏%':>9} {'$收益':>8} {'跳过':>6}")
print(f"{'─'*85}")

best = None
for r in all_results:
    ws = f"{r['w']}/{r['n']}={r['wr']:.0f}%" if r['n'] else "0"
    print(f"{r['name']:<28} {r['n']:>4} {ws:>7} {r['tg']:>+9.2f} {r['tf']:>+8.3f} {r['tn']:>+9.2f} {r['usd']:>+8.2f} {r['sv']+r['sm']:>5}根")
    if best is None or r['tn'] > best['tn']: best = r

# ===== 最佳详情 =====
if best and best["n"]:
    print(f"\n{'='*110}")
    print(f"🏆 {best['name']} | 净{best['tn']:+.2f}% | ${best['usd']:+.2f} | {best['w']}/{best['n']}={best['wr']:.0f}%")
    print(f"{'='*110}")
    print(f"{'方':^4} {'入场':^12} {'出场':^12} {'入场价':>9} {'出场价':>9} {'毛%':>7} {'净%(5x)':>9} {'持':>4} {'原因':^6}")
    print(f"{'─'*85}")
    
    # 按时间排序
    best["detail"].sort(key=lambda t: t["in"])
    for t in best["detail"]:
        d = "多" if t["dir"]=="long" else "空"
        g = f"{t['gross']:+5.2f}%"
        n = f"{t['net']:+7.2f}%"
        print(f"{d:^4} {t['in']:^12} {t['out']:^12} {t['ep']:>9.1f} {t['exit']:>9.1f} {g:>7} {n:>9} {t['hrs']:>3}h {t['reason']:^6}")
    print(f"{'─'*85}")
    
    wt = [t for t in best["detail"] if t["net"] > 0]
    lt = [t for t in best["detail"] if t["net"] <= 0]
    if wt and lt:
        aw = sum(t["net"] for t in wt)/len(wt)
        al = abs(sum(t["net"] for t in lt)/len(lt))
        print(f"平均盈利: +{aw:.2f}% | 平均亏损: -{al:.2f}% | 盈亏比: {aw/al:.2f}")
    if len(best["detail"]) > 1:
        pn = [t["net"] for t in best["detail"]]
        a = sum(pn)/len(pn); s = math.sqrt(sum((x-a)**2 for x in pn)/len(pn))
        print(f"夏普: {a/s*math.sqrt(len(pn)):.2f}" if s>0 else "夏普: N/A")
    
    avg_atr = sum(v for v in atr14_pct if v)/sum(1 for v in atr14_pct if v)
    print(f"\n📊 1H ATR(14): {avg_atr:.3f}% | 波动过滤跳过: {best['sv']}根 | MA缠绕跳过: {best['sm']}根")
    print(f"📊 日均交易: {best['n']/days_span:.1f}笔 | 数据跨度: {days_span:.1f}天")

print(f"\n{'='*110}")
