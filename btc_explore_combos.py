#!/usr/bin/env python3
"""
数据探索：扫描BTC 15分钟K线，找出最优指标组合
对每根K线计算所有指标，测试N种入场条件组合 → 统计胜率和盈亏
"""
import json, math
from datetime import datetime, timezone, timedelta
from itertools import product

# ===== 加载数据 =====
with open("/tmp/btc_15m_gate.json") as f:
    raw = json.load(f)
bars = []
for r in raw:
    bars.append({"ts": int(r[0]), "o": float(r[1]), "h": float(r[2]),
                 "l": float(r[3]), "c": float(r[4]),
                 "dt": datetime.fromtimestamp(int(r[0])/1000, tz=timezone.utc)})
bars.sort(key=lambda x: x["ts"])
n = len(bars)
closes = [b["c"] for b in bars]; highs = [b["h"] for b in bars]; lows = [b["l"] for b in bars]

# ===== 日线MA730 =====
import subprocess
daily_raw = subprocess.run(["okx","market","candles","BTC-USDT","--bar","1D","--limit","300","--json"],
                          capture_output=True, text=True, timeout=60)
daily_json = json.loads(daily_raw.stdout)
daily = []
for r in daily_json:
    daily.append({"ts": int(r[0]), "c": float(r[4]),
                  "dt": datetime.fromtimestamp(int(r[0])/1000, tz=timezone.utc)})
daily.sort(key=lambda x: x["ts"]); dc = [b["c"] for b in daily]
daily_ma_map = {}
for i, d in enumerate(daily):
    ds = d["dt"].strftime("%Y-%m-%d")
    n730 = min(730, i+1)
    daily_ma_map[ds] = sum(dc[i-n730+1:i+1])/n730

for bar in bars:
    ds = bar["dt"].strftime("%Y-%m-%d")
    bar["ma730"] = daily_ma_map.get(ds)
    if bar["ma730"] is None:
        bd = bar["dt"].date()
        best = None
        for dds, m in daily_ma_map.items():
            if datetime.strptime(dds, "%Y-%m-%d").date() <= bd: best = m
        bar["ma730"] = best

# ===== 计算所有指标 =====
print("计算指标...")

# MA系列
ma9_v, ma21_v, ma9_p, ma21_p = [], [], [], []
ma5_v, ma13_v, ma5_p, ma13_p = [], [], [], []
ma50_v, ma100_v = [], []
for i in range(n):
    if i >= 8:
        ma9_v.append(sum(closes[i-8:i+1])/9)
        ma9_p.append(sum(closes[i-9:i])/9 if i>=9 else None)
    else: ma9_v.append(None); ma9_p.append(None)
    if i >= 20:
        ma21_v.append(sum(closes[i-20:i+1])/21)
        ma21_p.append(sum(closes[i-21:i])/21 if i>=21 else None)
    else: ma21_v.append(None); ma21_p.append(None)
    if i >= 4:
        ma5_v.append(sum(closes[i-4:i+1])/5)
        ma5_p.append(sum(closes[i-5:i])/5 if i>=5 else None)
    else: ma5_v.append(None); ma5_p.append(None)
    if i >= 12:
        ma13_v.append(sum(closes[i-12:i+1])/13)
        ma13_p.append(sum(closes[i-13:i])/13 if i>=13 else None)
    else: ma13_v.append(None); ma13_p.append(None)
    if i >= 49: ma50_v.append(sum(closes[i-49:i+1])/50)
    else: ma50_v.append(None)
    if i >= 99: ma100_v.append(sum(closes[i-99:i+1])/100)
    else: ma100_v.append(None)

# BB(20,2)
bb_u, bb_l, bb_m = [], [], []
for i in range(n):
    if i >= 19:
        w=closes[i-19:i+1]; s=sum(w)/20; std=math.sqrt(sum((x-s)**2 for x in w)/20)
        bb_u.append(s+2*std); bb_l.append(s-2*std); bb_m.append(s)
    else: bb_u.append(None); bb_l.append(None); bb_m.append(None)

# RSI(14)
rsi = []
gains, losses = [], []
for i in range(n):
    if i==0: gains.append(0); losses.append(0)
    else: ch=closes[i]-closes[i-1]; gains.append(max(ch,0)); losses.append(max(-ch,0))
    if i>=14:
        ag=sum(gains[i-13:i+1])/14; al=sum(losses[i-13:i+1])/14
        rsi.append(100-100/(1+ag/al) if al>0 else 100)
    else: rsi.append(None)

# ADX(14)
tr_vals = []
for i in range(n):
    if i==0: tr_vals.append(highs[i]-lows[i])
    else: tr_vals.append(max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])))
def ws(arr, p):
    r=[] 
    for i in range(len(arr)):
        if i<p-1: r.append(None)
        elif i==p-1: r.append(sum(arr[:p]))
        else: r.append(r[-1]-r[-1]/p+arr[i])
    return r
atr14 = ws(tr_vals, 14)
pdm=[max(highs[i]-highs[i-1],0) if i>0 and highs[i]-highs[i-1]>lows[i-1]-lows[i] else 0 for i in range(n)]
ndm=[max(lows[i-1]-lows[i],0) if i>0 and lows[i-1]-lows[i]>highs[i]-highs[i-1] else 0 for i in range(n)]
pdm14=ws(pdm,14); ndm14=ws(ndm,14)
adx=[]
for i in range(n):
    if atr14[i] is None or atr14[i]==0: adx.append(None)
    else:
        pdi=pdm14[i]/atr14[i]*100; ndi=ndm14[i]/atr14[i]*100
        adx.append(abs(pdi-ndi)/(pdi+ndi)*100 if pdi+ndi>0 else 0)

# ATR%
atr_pct = [atr14[i]/closes[i]*100 if atr14[i] else None for i in range(n)]

# 动量: 最近N根涨跌幅
mom3 = [None]*3 + [(closes[i]-closes[i-3])/closes[i-3]*100 for i in range(3,n)]
mom6 = [None]*6 + [(closes[i]-closes[i-6])/closes[i-6]*100 for i in range(6,n)]
mom12 = [None]*12 + [(closes[i]-closes[i-12])/closes[i-12]*100 for i in range(12,n)]

# 高点到低点比例(近期振幅)
amp6 = []
for i in range(n):
    if i<5: amp6.append(None)
    else: amp6.append((max(highs[i-5:i+1])-min(lows[i-5:i+1]))/closes[i]*100)

# 赋值
for i, bar in enumerate(bars):
    bar["idx"] = i
    bar["ma9"]=ma9_v[i]; bar["ma21"]=ma21_v[i]; bar["ma9p"]=ma9_p[i]; bar["ma21p"]=ma21_p[i]
    bar["ma5"]=ma5_v[i]; bar["ma13"]=ma13_v[i]; bar["ma5p"]=ma5_p[i]; bar["ma13p"]=ma13_p[i]
    bar["ma50"]=ma50_v[i]; bar["ma100"]=ma100_v[i]
    bar["bb_u"]=bb_u[i]; bar["bb_l"]=bb_l[i]; bar["bb_m"]=bb_m[i]
    bar["rsi"]=rsi[i]; bar["adx"]=adx[i]; bar["atr_pct"]=atr_pct[i]
    bar["mom3"]=mom3[i]; bar["mom6"]=mom6[i]; bar["mom12"]=mom12[i]
    bar["amp6"]=amp6[i]

# 只取有效的bar(前面指标已预热)
valid_start = 100  # 跳过前100根，等所有指标就绪
print(f"有效K线: {n-valid_start} 根 (跳过前{valid_start}根预热)")

# ===== 定义入场条件 =====
# 每个条件返回 (signal: 'long'/'short'/None)
def check_condition(bar, cond_id):
    c = bar["c"]; m7 = bar.get("ma730")
    if None in (c, m7): return None
    
    # 基础方向
    below_ma730 = c < m7
    above_ma730 = c > m7
    near_ma730 = abs(c-m7)/m7 < 0.01
    
    m50 = bar.get("ma50"); m100 = bar.get("ma100")
    
    # MA交叉
    ma9_cross_up = (bar.get("ma9p") is not None and bar.get("ma21p") is not None 
                    and bar["ma9p"] <= bar["ma21p"] and bar["ma9"] > bar["ma21"])
    ma9_cross_dn = (bar.get("ma9p") is not None and bar.get("ma21p") is not None 
                    and bar["ma9p"] >= bar["ma21p"] and bar["ma9"] < bar["ma21"])
    ma5_cross_up = (bar.get("ma5p") is not None and bar.get("ma13p") is not None 
                    and bar["ma5p"] <= bar["ma13p"] and bar["ma5"] > bar["ma13"])
    ma5_cross_dn = (bar.get("ma5p") is not None and bar.get("ma13p") is not None 
                    and bar["ma5p"] >= bar["ma13p"] and bar["ma5"] < bar["ma13"])
    
    # BB
    bb_above = bar.get("bb_u") and c > bar["bb_u"]
    bb_below = bar.get("bb_l") and c < bar["bb_l"]
    bb_inside = bar.get("bb_u") and bar.get("bb_l") and bar["bb_l"] < c < bar["bb_u"]
    bb_mid = bar.get("bb_m")
    
    # RSI
    r = bar.get("rsi")
    rsi_ob = r and r > 70
    rsi_os = r and r < 30
    rsi_high = r and r > 60
    rsi_low = r and r < 40
    
    # ADX
    a = bar.get("adx")
    adx_trend = a and a > 25
    adx_range = a and a <= 25
    adx_strong = a and a > 30
    
    # 动量
    mom3_up = bar.get("mom3") and bar["mom3"] > 0
    mom3_dn = bar.get("mom3") and bar["mom3"] < 0
    mom6_up = bar.get("mom6") and bar["mom6"] > 0
    mom6_dn = bar.get("mom6") and bar["mom6"] < 0
    
    # ATR
    atr_low = bar.get("atr_pct") and bar["atr_pct"] < 0.3
    atr_high = bar.get("atr_pct") and bar["atr_pct"] > 0.6
    
    # 振幅
    amp_low = bar.get("amp6") and bar["amp6"] < 1.0
    amp_high = bar.get("amp6") and bar["amp6"] > 2.0
    
    if near_ma730: return None
    
    # 条件组合
    if cond_id == "A1_ma9cross_downtrend":
        return 'short' if ma9_cross_dn and below_ma730 else None
    if cond_id == "A2_ma9cross_downtrend_strong":
        return 'short' if ma9_cross_dn and below_ma730 and adx_trend else None
    if cond_id == "A3_ma5cross_downtrend":
        return 'short' if ma5_cross_dn and below_ma730 else None
    if cond_id == "A4_ma5cross_downtrend_adx":
        return 'short' if ma5_cross_dn and below_ma730 and adx_trend else None
    if cond_id == "B1_bb_short":
        return 'short' if bb_above and rsi_high and below_ma730 else None
    if cond_id == "B2_bb_long":
        return 'long' if bb_below and rsi_low and above_ma730 else None
    if cond_id == "B3_bb_short_narrow":
        return 'short' if bb_above and rsi_high and below_ma730 and adx_range else None
    if cond_id == "B4_bb_long_narrow":
        return 'long' if bb_below and rsi_low and above_ma730 and adx_range else None
    if cond_id == "C1_momentum_short":
        return 'short' if mom6_dn and below_ma730 and c < (m50 or c) else None
    if cond_id == "C2_momentum_long":
        return 'long' if mom6_up and above_ma730 and c > (m50 or c) else None
    if cond_id == "D1_rsi_divergence_short":
        return 'short' if rsi_ob and below_ma730 and adx_range else None
    if cond_id == "D2_rsi_divergence_long":
        return 'long' if rsi_os and above_ma730 and adx_range else None
    if cond_id == "E1_ma_pullback_short":
        return 'short' if below_ma730 and c > (m50 or c) and rsi_high else None
    if cond_id == "E2_atr_breakout_short":
        return 'short' if below_ma730 and atr_high and c < (bar["ma21"] or c) and mom3_dn else None
    if cond_id == "F1_ma_cross_any":
        return 'short' if (ma9_cross_dn or ma5_cross_dn) and below_ma730 else ('long' if (ma9_cross_up or ma5_cross_up) and above_ma730 else None)
    if cond_id == "F2_bb_any":
        return 'short' if bb_above and rsi_high and below_ma730 else ('long' if bb_below and rsi_low and above_ma730 else None)
    if cond_id == "G1_combined_best":
        # 综合: MA交叉趋势+BB震荡
        if adx_trend:
            return 'short' if ma5_cross_dn and below_ma730 else ('long' if ma5_cross_up and above_ma730 else None)
        else:
            return 'short' if bb_above and r > 65 and below_ma730 else ('long' if bb_below and r < 35 and above_ma730 else None)
    
    return None

condition_ids = [
    "A1_ma9cross_downtrend", "A2_ma9cross_downtrend_strong", 
    "A3_ma5cross_downtrend", "A4_ma5cross_downtrend_adx",
    "B1_bb_short", "B2_bb_long", "B3_bb_short_narrow", "B4_bb_long_narrow",
    "C1_momentum_short", "C2_momentum_long",
    "D1_rsi_divergence_short", "D2_rsi_divergence_long",
    "E1_ma_pullback_short", "E2_atr_breakout_short",
    "F1_ma_cross_any", "F2_bb_any", "G1_combined_best"
]

# ===== 测试每种条件+T/S组合 =====
TP_LIST = [0.3, 0.4, 0.5, 0.6, 0.8, 1.0]
SL_LIST = [0.2, 0.25, 0.3, 0.35, 0.4, 0.5]
MAXB_LIST = [6, 8, 10, 12, 16, 20]
FEE = 0.07; LEV = 5

print(f"\n扫描 {len(condition_ids)} 种入场 × {len(TP_LIST)}×{len(SL_LIST)}×{len(MAXB_LIST)} 种离场 = {len(condition_ids)*len(TP_LIST)*len(SL_LIST)*len(MAXB_LIST)} 组合...")

results = []
for cond_id in condition_ids:
    for TP in TP_LIST:
        for SL in SL_LIST:
            if SL >= TP: continue
            for MB in MAXB_LIST:
                trades = []; pos = None
                
                for gi in range(valid_start, n):
                    bar = bars[gi]
                    signal = check_condition(bar, cond_id)
                    
                    if pos is not None:
                        c = bar["c"]; ep = pos["price"]; ei = pos["idx"]; held = gi - ei
                        gp = (c-ep)/ep*100 if pos["type"]=="long" else (ep-c)/ep*100
                        
                        reason = None
                        if gp >= TP: reason = "tp"
                        elif gp <= -SL: reason = "sl"
                        elif held >= MB: reason = "to"
                        
                        if reason:
                            net = (gp - FEE) * LEV
                            trades.append({"dir":pos["type"],"net":net,"gp":gp,"reason":reason,"held":held})
                            pos = None
                        continue
                    
                    if signal:
                        pos = {"type": signal, "idx": gi, "price": bar["c"]}
                
                if pos:
                    c = bars[-1]["c"]; ep = pos["price"]
                    gp = (c-ep)/ep*100 if pos["type"]=="long" else (ep-c)/ep*100
                    net = (gp - FEE) * LEV
                    trades.append({"dir":pos["type"],"net":net,"gp":gp,"reason":"end","held":n-1-pos["idx"]})
                
                if len(trades) < 10: continue
                
                w = sum(1 for t in trades if t["net"] > 0)
                tn = sum(t["net"] for t in trades)
                wr = w/len(trades)*100
                
                wt = [t["net"] for t in trades if t["net"]>0]
                lt = [t["net"] for t in trades if t["net"]<=0]
                rr = (sum(wt)/len(wt))/(abs(sum(lt)/len(lt))) if wt and lt else 0
                
                if len(trades)>1:
                    pn=[t["net"] for t in trades]; a=sum(pn)/len(trades)
                    s=math.sqrt(sum((x-a)**2 for x in pn)/len(trades))
                    sh=a/s*math.sqrt(len(trades)) if s>0 else 0
                else: sh=0
                
                # 综合评分
                score = tn*0.3 + sh*0.2 + wr*0.3 + rr*30*0.2
                
                results.append({
                    "cond":cond_id, "tp":TP, "sl":SL, "mb":MB,
                    "n":len(trades), "w":w, "wr":wr, "tn":tn, "sh":sh, "rr":rr,
                    "score":score, "usd":tn/100*37.54, "trades":trades
                })

# ===== 排序和输出 =====
results.sort(key=lambda x: -x["score"])

print(f"\n{'='*120}")
print(f"🏆 Top 30 组合 (按综合评分)")
print(f"{'='*120}")
print(f"{'排名':<5} {'入场条件':<30} {'TP/SL/MB':<16} {'笔':>4} {'胜率':>7} {'净%':>9} {'$':>7} {'夏普':>6} {'RR':>5} {'评分':>7}")
print(f"{'─'*100}")

for i, r in enumerate(results[:30]):
    tp_sl = f"TP{r['tp']}/SL{r['sl']}/{r['mb']}b"
    print(f"{i+1:<5} {r['cond']:<30} {tp_sl:<16} {r['n']:>4} {r['w']}/{r['n']}={r['wr']:.0f}% {r['tn']:>+9.2f} {r['usd']:>+7.2f} {r['sh']:>6.2f} {r['rr']:>5.2f} {r['score']:>7.1f}")

# 按条件聚合最佳
print(f"\n{'='*120}")
print(f"📊 各入场条件的最优参数")
print(f"{'='*120}")
for cond_id in condition_ids:
    cond_results = [r for r in results if r["cond"]==cond_id]
    if not cond_results: continue
    best = max(cond_results, key=lambda x: x["score"])
    print(f"  {cond_id:<32} TP{best['tp']}/SL{best['sl']}/{best['mb']}b | {best['n']}笔 胜{best['wr']:.0f}% 净{best['tn']:+.2f}% ${best['usd']:+.2f} 夏普{best['sh']:.2f}")

# 最佳组合详情
best = results[0]
print(f"\n{'='*120}")
print(f"🌟 全局最佳: {best['cond']} | TP{best['tp']}/SL{best['sl']}/{best['mb']}b")
print(f"   {best['n']}笔 | 胜率{best['wr']:.0f}% | 净{best['tn']:+.2f}% | ${best['usd']:+.2f} | 夏普{best['sh']:.2f} | RR{best['rr']:.2f}")
print(f"   评分: {best['score']:.1f}")

# 日期分布
print(f"\n   逐笔:")
for t in sorted(enumerate(best["trades"]), key=lambda x: x[1].get("_dt","")):
    pass  # 没有时间信息在trades里

# 统计正收益组合
positive = [r for r in results if r["tn"] > 0]
print(f"\n📈 正收益组合: {len(positive)}/{len(results)} ({len(positive)/len(results)*100:.1f}%)")
if positive:
    print(f"   最佳正收益: {positive[0]['cond']} TP{positive[0]['tp']}/SL{positive[0]['sl']}/{positive[0]['mb']}b | {positive[0]['tn']:+.2f}%")
