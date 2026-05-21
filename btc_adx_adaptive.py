#!/usr/bin/env python3
"""
BTC 15分钟 ADX自适应策略: ADX>25趋势用MA交叉, ADX<25震荡用BB+RSI
"""
import json, math
from datetime import datetime, timezone, timedelta

# ===== 数据 =====
with open("/tmp/btc_15m_gate.json") as f:
    raw = json.load(f)
bars = []
for r in raw:
    bars.append({"ts": int(r[0]), "o": float(r[1]), "h": float(r[2]),
                 "l": float(r[3]), "c": float(r[4]),
                 "dt": datetime.fromtimestamp(int(r[0])/1000, tz=timezone.utc)})
bars.sort(key=lambda x: x["ts"])

import subprocess
daily_raw = subprocess.run(["okx","market","candles","BTC-USDT","--bar","1D","--limit","300","--json"],
                          capture_output=True, text=True, timeout=60)
daily_json = json.loads(daily_raw.stdout)
daily = []
for r in daily_json:
    daily.append({"ts": int(r[0]), "c": float(r[4]),
                  "dt": datetime.fromtimestamp(int(r[0])/1000, tz=timezone.utc)})
daily.sort(key=lambda x: x["ts"]); nd = len(daily); dc = [b["c"] for b in daily]
daily_ma = {}
for i, d in enumerate(daily):
    ds = d["dt"].strftime("%Y-%m-%d")
    n730 = min(730, i+1)
    daily_ma[ds] = sum(dc[i-n730+1:i+1])/n730

for bar in bars:
    ds = bar["dt"].strftime("%Y-%m-%d")
    bar["ma730"] = daily_ma.get(ds)
    if bar["ma730"] is None:
        bd = bar["dt"].date()
        best = None
        for dds, m in daily_ma.items():
            if datetime.strptime(dds, "%Y-%m-%d").date() <= bd: best = m
        bar["ma730"] = best

# ===== 计算所有指标 =====
closes = [b["c"] for b in bars]
highs = [b["h"] for b in bars]; lows = [b["l"] for b in bars]
n = len(bars)

# ADX(14)
tr_vals, plus_dm, minus_dm = [], [], []
for i in range(n):
    if i == 0: tr_vals.append(highs[i]-lows[i]); plus_dm.append(0); minus_dm.append(0)
    else:
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        tr_vals.append(tr)
        up = highs[i] - highs[i-1]; dn = lows[i-1] - lows[i]
        plus_dm.append(up if up > dn and up > 0 else 0)
        minus_dm.append(dn if dn > up and dn > 0 else 0)

def wilder_smooth(arr, period):
    result = []
    for i in range(len(arr)):
        if i < period-1: result.append(None)
        elif i == period-1: result.append(sum(arr[:period]))
        else: result.append(result[-1] - result[-1]/period + arr[i])
    return result

atr14 = wilder_smooth(tr_vals, 14)
pdm14 = wilder_smooth(plus_dm, 14)
ndm14 = wilder_smooth(minus_dm, 14)
adx = []
for i in range(n):
    if atr14[i] is None or atr14[i] == 0:
        adx.append(None)
    else:
        pdi = pdm14[i] / atr14[i] * 100
        ndi = ndm14[i] / atr14[i] * 100
        if pdi + ndi == 0: adx.append(0)
        else:
            dx = abs(pdi - ndi) / (pdi + ndi) * 100
            adx.append(dx)

# 对ADX做平滑(14)
adx_smooth = []
for i in range(n):
    if i < 13: adx_smooth.append(adx[i])
    elif None in adx[i-13:i+1]: adx_smooth.append(None)
    else: adx_smooth.append(sum(adx[i-13:i+1])/14)

# MA9, MA21
ma9_v, ma21_v, ma9_p, ma21_p = [], [], [], []
for i in range(n):
    if i >= 8:
        ma9_v.append(sum(closes[i-8:i+1])/9)
        ma9_p.append(sum(closes[i-9:i])/9 if i>=9 else None)
    else: ma9_v.append(None); ma9_p.append(None)
    if i >= 20:
        ma21_v.append(sum(closes[i-20:i+1])/21)
        ma21_p.append(sum(closes[i-21:i])/21 if i>=21 else None)
    else: ma21_v.append(None); ma21_p.append(None)

# BB(20,2), RSI(14)
sma20, bb_u, bb_l, bb_m = [], [], [], []
for i in range(n):
    if i >= 19:
        w = closes[i-19:i+1]; s = sum(w)/20
        std = math.sqrt(sum((x-s)**2 for x in w)/20)
        sma20.append(s); bb_u.append(s+2*std); bb_l.append(s-2*std); bb_m.append(s)
    else: sma20.append(None); bb_u.append(None); bb_l.append(None); bb_m.append(None)

rsi = []; gains, losses = [], []
for i in range(n):
    if i==0: gains.append(0); losses.append(0)
    else: ch=closes[i]-closes[i-1]; gains.append(max(ch,0)); losses.append(max(-ch,0))
    if i>=14:
        avg_g=sum(gains[i-13:i+1])/14; avg_l=sum(losses[i-13:i+1])/14
        rsi.append(100-100/(1+avg_g/avg_l) if avg_l>0 else 100)
    else: rsi.append(None)

for i, bar in enumerate(bars):
    bar["adx"] = adx_smooth[i]
    bar["ma9"] = ma9_v[i]; bar["ma21"] = ma21_v[i]
    bar["ma9p"] = ma9_p[i]; bar["ma21p"] = ma21_p[i]
    bar["bb_u"] = bb_u[i]; bar["bb_l"] = bb_l[i]; bar["bb_m"] = bb_m[i]
    bar["rsi"] = rsi[i]

# ===== 回测 =====
FEE = 0.07; LEV = 5; ADX_THRESH = 25
PERIODS = [15, 30, 60, 90]
now = datetime.now(timezone.utc)

def run_adaptive(subset, trend_tp, trend_sl, trend_mb,
                 range_tp, range_sl, range_mb):
    trades = []; pos = None
    
    for gi, bar in enumerate(subset):
        c = bar["c"]; m7 = bar.get("ma730")
        adxv = bar.get("adx")
        if None in (c, m7, adxv): continue
        
        is_trend = adxv > ADX_THRESH
        
        if pos is not None:
            ep = pos["price"]; ei = pos["idx"]; held = gi - ei
            gp = (c-ep)/ep*100 if pos["type"]=="long" else (ep-c)/ep*100
            
            # 根据入场时的模式决定出场参数
            tp = trend_tp if pos.get("mode")=="trend" else range_tp
            sl = trend_sl if pos.get("mode")=="trend" else range_sl
            mb = trend_mb if pos.get("mode")=="trend" else range_mb
            
            reason = None
            if gp >= tp: reason = "tp"
            elif gp <= -sl: reason = "sl"
            elif held >= mb: reason = "timeout"
            
            if reason:
                net = (gp - FEE) * LEV
                trades.append({"dir":pos["type"],"gp":round(gp,4),"net":round(net,4),
                              "held":held,"reason":reason,"mode":pos.get("mode","?"),
                              "in_dt":subset[ei]["dt"],"out_dt":bar["dt"]})
                pos = None
            continue
        
        if is_trend:
            # 趋势模式: MA9/MA21交叉 + MA730方向
            m9=bar.get("ma9"); m21=bar.get("ma21"); m9p=bar.get("ma9p"); m21p=bar.get("ma21p")
            if None in (m9,m21,m9p,m21p): continue
            
            nm = abs(c-m7)/m7 < 0.01
            tu = c > m7; td = c < m7
            gc = m9p <= m21p and m9 > m21
            dc = m9p >= m21p and m9 < m21
            
            if nm: continue
            if tu and gc:
                pos = {"type":"long","idx":gi,"price":c,"mode":"trend"}
            elif td and dc:
                pos = {"type":"short","idx":gi,"price":c,"mode":"trend"}
        else:
            # 震荡模式: BB+RSI
            bu=bar.get("bb_u"); bl=bar.get("bb_l"); r=bar.get("rsi")
            if None in (bu,bl,r): continue
            
            # 只做反弹方向：熊市只做空反弹，牛市只做多回调
            if c > bu and r > 65 and c < m7:
                pos = {"type":"short","idx":gi,"price":c,"mode":"range"}
            elif c < bl and r < 35 and c > m7:
                pos = {"type":"long","idx":gi,"price":c,"mode":"range"}
    
    if pos:
        lb=subset[-1]; c=lb["c"]; ep=pos["price"]
        gp = (c-ep)/ep*100 if pos["type"]=="long" else (ep-c)/ep*100
        held=len(subset)-1-pos["idx"]
        net=(gp-FEE)*LEV
        trades.append({"dir":pos["type"],"gp":round(gp,4),"net":round(net,4),
                      "held":held,"reason":"end","mode":pos.get("mode","?"),
                      "in_dt":subset[pos["idx"]]["dt"],"out_dt":lb["dt"]})
    
    w=sum(1 for t in trades if t["net"]>0); n=len(trades)
    tn=sum(t["net"] for t in trades); usd=tn/100*37.54
    wr=w/n*100 if n else 0
    wt=[t["net"] for t in trades if t["net"]>0]
    lt=[t["net"] for t in trades if t["net"]<=0]
    rr=(sum(wt)/len(wt))/(abs(sum(lt)/len(lt))) if wt and lt else 0
    if n>1:
        pn=[t["net"] for t in trades]; a=sum(pn)/n
        s=math.sqrt(sum((x-a)**2 for x in pn)/n)
        sh=a/s*math.sqrt(n) if s>0 else 0
    else: sh=0
    return {"n":n,"w":w,"wr":wr,"tn":tn,"usd":usd,"rr":rr,"sh":sh,"trades":trades}

# 参数组合
combos = [
    # (trend_tp,trend_sl,trend_mb, range_tp,range_sl,range_mb)
    (0.60, 0.35, 14, 0.80, 0.40, 24, "T0.6/0.35/14b R0.8/0.4/24b"),
    (0.50, 0.30, 12, 0.80, 0.40, 24, "T0.5/0.3/12b R0.8/0.4/24b"),
    (0.60, 0.35, 14, 0.50, 0.30, 16, "T0.6/0.35/14b R0.5/0.3/16b"),
    (0.80, 0.40, 16, 0.80, 0.40, 24, "T0.8/0.4/16b R0.8/0.4/24b"),
    (0.40, 0.25, 10, 0.60, 0.35, 20, "T0.4/0.25/10b R0.6/0.35/20b"),
]

print(f"\n{'='*120}")
print(f"ADX自适应策略: ADX>{ADX_THRESH}=趋势(MA交叉) | ADX<{ADX_THRESH}=震荡(BB+RSI)")
print(f"maker+taker={FEE}% | {LEV}x | $37.54")
print(f"{'='*120}")

for period_days in PERIODS:
    cutoff = now - timedelta(days=period_days)
    cutoff_ts = int(cutoff.timestamp() * 1000)
    subset = [b for b in bars if b["ts"] >= cutoff_ts]
    if len(subset) < 100: continue
    
    # 统计ADX分布
    adx_vals = [b.get("adx") for b in subset if b.get("adx") is not None]
    trend_pct = sum(1 for a in adx_vals if a > ADX_THRESH) / len(adx_vals) * 100 if adx_vals else 0
    
    print(f"\n{'─'*120}")
    print(f"📅 {period_days}天 ({subset[0]['dt'].strftime('%m-%d')}~{subset[-1]['dt'].strftime('%m-%d')}, {len(subset)}根, 趋势{trend_pct:.0f}%/震荡{100-trend_pct:.0f}%)")
    print(f"{'─'*120}")
    
    best = None; bs = -999
    
    for ttp, tsl, tmb, rtp, rsl, rmb, name in combos:
        r = run_adaptive(subset, ttp, tsl, tmb, rtp, rsl, rmb)
        if r["n"] == 0: continue
        score = r["tn"]*0.4 + r["sh"]*0.3 + r["wr"]*0.3
        if score > bs: bs = score; best = {"name":name, **r}
        print(f"  {name:<28} {r['n']:>4}笔 胜{r['w']}/{r['n']}={r['wr']:.0f}%  净{r['tn']:>+8.2f}%  ${r['usd']:>+7.2f}  夏普{r['sh']:>6.2f}  RR{r['rr']:.2f}")
    
    if best:
        # 统计模式分布
        tm = sum(1 for t in best["trades"] if t.get("mode")=="trend")
        rm = sum(1 for t in best["trades"] if t.get("mode")=="range")
        print(f"\n  🏆 {best['name']} | {best['n']}笔(趋势{tm}/震荡{rm}) | 胜{best['wr']:.0f}% | 净{best['tn']:+.2f}% | ${best['usd']:+.2f}")
        
        # 趋势模式 vs 震荡模式分别统计
        for mode, label in [("trend","趋势"), ("range","震荡")]:
            mt = [t for t in best["trades"] if t.get("mode")==mode]
            if mt:
                mw = sum(1 for t in mt if t["net"]>0)
                print(f"    {label}模式: {len(mt)}笔 胜{mw}/{len(mt)}={mw/len(mt)*100:.0f}% 盈亏{sum(t['net'] for t in mt):+.2f}%")

# ===== 最终汇总 =====
print(f"\n{'='*120}")
print(f"📊 各周期最优参数")
print(f"{'='*120}")
print(f"{'周期':<8} {'参数':<30} {'笔':>4} {'胜率':>7} {'净%':>9} {'$':>7} {'夏普':>6} {'趋势/震荡':>10}")
print(f"{'─'*95}")

for period_days in PERIODS:
    cutoff = now - timedelta(days=period_days)
    cutoff_ts = int(cutoff.timestamp() * 1000)
    subset = [b for b in bars if b["ts"] >= cutoff_ts]
    if len(subset) < 100: continue
    
    best = None; bs = -999
    for ttp, tsl, tmb, rtp, rsl, rmb, name in combos:
        r = run_adaptive(subset, ttp, tsl, tmb, rtp, rsl, rmb)
        if r["n"]==0: continue
        s = r["tn"]*0.4+r["sh"]*0.3+r["wr"]*0.3
        if s>bs: bs=s; best={"name":name,**r}
    
    if best:
        tm=sum(1 for t in best["trades"] if t.get("mode")=="trend")
        rm=sum(1 for t in best["trades"] if t.get("mode")=="range")
        print(f"{period_days:>4}天  {best['name']:<30} {best['n']:>4} {best['w']}/{best['n']}={best['wr']:.0f}% {best['tn']:>+9.2f} {best['usd']:>+7.2f} {best['sh']:>6.2f} {tm}/{rm}")

print(f"\n数据: {len(bars)}根15分钟 | 93天")
