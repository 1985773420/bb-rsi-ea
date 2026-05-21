#!/usr/bin/env python3
"""
BTC 15分钟 全周期回测 (15/30/60/90天)
策略: MA730方向 + MA200过滤 + MA9/21交叉 + ATR波动过滤 + maker入场
数据: Gate.io 9000根15分钟K线 + OKX 300天日线
"""
import json, math
from datetime import datetime, timezone, timedelta

# ===== 加载数据 =====
with open("/tmp/btc_15m_gate.json") as f:
    raw = json.load(f)

# 解析: [ts_ms_str, o, h, l, c, vol, vol_base]
bars = []
for r in raw:
    bars.append({
        "ts": int(r[0]), "o": float(r[1]), "h": float(r[2]),
        "l": float(r[3]), "c": float(r[4]), "v": float(r[5]),
        "dt": datetime.fromtimestamp(int(r[0])/1000, tz=timezone.utc)
    })
bars.sort(key=lambda x: x["ts"])
print(f"15分钟K线: {len(bars)} 条")
print(f"时间: {bars[0]['dt']} ~ {bars[-1]['dt']}")
print(f"跨度: {(bars[-1]['dt'] - bars[0]['dt']).days} 天")

# ===== 日线数据 (从OKX获取) =====
import subprocess
def okx_cmd(args):
    r = subprocess.run(["okx"] + args, capture_output=True, text=True, timeout=60)
    return json.loads(r.stdout)

print("拉取OKX日线...")
daily_raw = okx_cmd(["market", "candles", "BTC-USDT", "--bar", "1D", "--limit", "300", "--json"])
daily = []
for r in daily_raw:
    daily.append({
        "ts": int(r[0]), "o": float(r[1]), "h": float(r[2]),
        "l": float(r[3]), "c": float(r[4]),
        "dt": datetime.fromtimestamp(int(r[0])/1000, tz=timezone.utc)
    })
daily.sort(key=lambda x: x["ts"])
dc = [b["c"] for b in daily]
nd = len(daily)
print(f"日线: {nd} 条, {daily[0]['dt'].date()} ~ {daily[-1]['dt'].date()}")

# 为每个日期预计算日线MA730和MA200
# daily_ma_map[date_str] = (ma730, ma200)
daily_ma_map = {}
for i, d in enumerate(daily):
    date_str = d["dt"].strftime("%Y-%m-%d")
    if i >= 199:
        ma200 = sum(dc[i-199:i+1]) / 200
    else:
        ma200 = sum(dc[:i+1]) / (i+1)
    n730 = min(730, i+1)
    ma730 = sum(dc[i-n730+1:i+1]) / n730
    daily_ma_map[date_str] = (ma730, ma200)

# 为每个15分钟K线匹配日线MA
for bar in bars:
    date_str = bar["dt"].strftime("%Y-%m-%d")
    if date_str in daily_ma_map:
        bar["ma730"], bar["ma200"] = daily_ma_map[date_str]
    else:
        # 找最近的日期
        bar_date = bar["dt"].date()
        best = None
        for ds, (m7, m2) in daily_ma_map.items():
            d = datetime.strptime(ds, "%Y-%m-%d").date()
            if d <= bar_date:
                best = (m7, m2)
        bar["ma730"], bar["ma200"] = best if best else (None, None)

# ===== 计算15分钟级别MA9, MA21, ATR =====
closes = [b["c"] for b in bars]
highs = [b["h"] for b in bars]
lows = [b["l"] for b in bars]

ma9_v, ma21_v, ma9_p, ma21_p = [], [], [], []
for i in range(len(closes)):
    if i >= 8:
        ma9_v.append(sum(closes[i-8:i+1])/9)
        ma9_p.append(sum(closes[i-9:i])/9 if i>=9 else None)
    else: ma9_v.append(None); ma9_p.append(None)
    if i >= 20:
        ma21_v.append(sum(closes[i-20:i+1])/21)
        ma21_p.append(sum(closes[i-21:i])/21 if i>=21 else None)
    else: ma21_v.append(None); ma21_p.append(None)

tr = []
for i in range(len(closes)):
    if i==0: tr.append(highs[i]-lows[i])
    else: tr.append(max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])))
atr_pct = [sum(tr[max(0,i-13):i+1])/min(i+1,14)/closes[i]*100 for i in range(len(closes))]
atr_m20 = []
for i in range(len(atr_pct)):
    if i>=19:
        vv=[v for v in atr_pct[i-19:i+1] if v]
        atr_m20.append(sum(vv)/len(vv) if vv else None)
    else: atr_m20.append(None)

for i, bar in enumerate(bars):
    bar["ma9"] = ma9_v[i]; bar["ma21"] = ma21_v[i]
    bar["ma9p"] = ma9_p[i]; bar["ma21p"] = ma21_p[i]
    bar["atr"] = atr_pct[i]; bar["atr_m"] = atr_m20[i]

# ===== 回测参数 =====
FEE = 0.07   # maker 0.02% + taker 0.05%
LEV = 5
VOL_RATIO = 0.70
NEAR_MA = 0.01  # MA730 ±1%

# 参数网格
TP_OPTS = [0.40, 0.50, 0.60, 0.80]
SL_OPTS = [0.25, 0.30, 0.35, 0.45]
MAXB_OPTS = [8, 10, 12, 14]  # 15分钟K线数

# 回测周期
PERIODS = [15, 30, 60, 90]

def run_backtest(bars_subset, TP, SL, MAX_BARS, use_filter):
    trades = []; pos = None; sv = 0; sm = 0
    
    for gi, bar in enumerate(bars_subset):
        c = bar["c"]
        m7 = bar.get("ma730"); m2 = bar.get("ma200")
        m9 = bar.get("ma9"); m21 = bar.get("ma21")
        m9p = bar.get("ma9p"); m21p = bar.get("ma21p")
        a = bar.get("atr"); am = bar.get("atr_m")
        
        if None in (m7, m2, m9, m21, m9p, m21p, a, am): continue
        
        tu = c > m7; td = c < m7
        nm = abs(c-m7)/m7 < NEAR_MA
        su = c > m2; sd = c < m2
        gc = m9p <= m21p and m9 > m21
        dc = m9p >= m21p and m9 < m21
        lv = use_filter and a < am * VOL_RATIO
        
        if pos is not None:
            ep = pos["price"]; ei = pos["idx"]; held = gi - ei
            gp = (c-ep)/ep*100 if pos["type"]=="long" else (ep-c)/ep*100
            
            reason = None
            if gp >= TP: reason = "tp"
            elif gp <= -SL: reason = "sl"
            elif pos["type"]=="long" and (td or dc): reason = "rev"
            elif pos["type"]=="short" and (tu or gc): reason = "rev"
            elif held >= MAX_BARS: reason = "timeout"
            
            if reason:
                net = (gp - FEE) * LEV
                trades.append({
                    "dir": pos["type"], "gp": round(gp,4), "net": round(net,4),
                    "held": held, "reason": reason,
                    "in_dt": bars_subset[ei]["dt"], "out_dt": bar["dt"]
                })
                pos = None
            continue
        
        if nm: sm += 1; continue
        if lv: sv += 1; continue
        
        if tu and su and gc:
            pos = {"type": "long", "idx": gi, "price": c}
        elif td and sd and dc:
            pos = {"type": "short", "idx": gi, "price": c}
    
    if pos:
        lb = bars_subset[-1]; c = lb["c"]; ep = pos["price"]
        gp = (c-ep)/ep*100 if pos["type"]=="long" else (ep-c)/ep*100
        held = len(bars_subset)-1-pos["idx"]
        net = (gp - FEE) * LEV
        trades.append({
            "dir": pos["type"], "gp": round(gp,4), "net": round(net,4),
            "held": held, "reason": "end",
            "in_dt": bars_subset[pos["idx"]]["dt"], "out_dt": lb["dt"]
        })
    
    w = sum(1 for t in trades if t["net"] > 0)
    tn = sum(t["net"] for t in trades)
    n = len(trades)
    wr = w/n*100 if n else 0
    usd = tn/100*37.54
    
    # 盈亏比
    wt = [t["net"] for t in trades if t["net"]>0]
    lt = [t["net"] for t in trades if t["net"]<=0]
    rr = (sum(wt)/len(wt)) / (abs(sum(lt)/len(lt))) if wt and lt else 0
    
    # 夏普
    if n > 1:
        pn = [t["net"] for t in trades]
        a = sum(pn)/n; s = math.sqrt(sum((x-a)**2 for x in pn)/n)
        sharpe = a/s*math.sqrt(n) if s>0 else 0
    else:
        sharpe = 0
    
    return {"n":n, "w":w, "wr":wr, "tn":tn, "usd":usd, "rr":rr, "sharpe":sharpe, "trades":trades}

# ===== 跑所有组合 =====
print(f"\n{'='*120}")
print(f"BTC 15分钟 MA9/21 + MA730方向 + MA200过滤 + ATR波动过滤")
print(f"maker(0.02%)+taker(0.05%)={FEE}% | {LEV}x | $37.54 | NEAR_MA={NEAR_MA*100:.0f}% | VOL<{VOL_RATIO*100:.0f}%ATR")
print(f"{'='*120}")

now = datetime.now(timezone.utc)
best_global = None

for period_days in PERIODS:
    cutoff = now - timedelta(days=period_days)
    cutoff_ts = int(cutoff.timestamp() * 1000)
    subset = [b for b in bars if b["ts"] >= cutoff_ts]
    
    if not subset:
        print(f"\n{period_days}天: 无数据")
        continue
    
    days_actual = (subset[-1]["dt"] - subset[0]["dt"]).days
    bars_per_day = len(subset) / max(days_actual, 0.1)
    
    print(f"\n{'─'*120}")
    print(f"📅 {period_days}天回测 ({subset[0]['dt'].strftime('%m-%d')}~{subset[-1]['dt'].strftime('%m-%d')}, {len(subset)}根, {bars_per_day:.0f}根/天)")
    print(f"{'─'*120}")
    
    best_period = None
    best_rr_score = -999
    
    for TP in TP_OPTS:
        for SL in SL_OPTS:
            if SL >= TP: continue
            for MB in MAXB_OPTS:
                for vf in [True, False]:
                    r = run_backtest(subset, TP, SL, MB, vf)
                    if r["n"] == 0: continue
                    
                    # 综合评分: 收益 + 夏普 + 胜率加权
                    score = r["tn"] * 0.4 + r["sharpe"] * 0.3 + r["wr"] * 0.3
                    
                    if score > best_rr_score:
                        best_rr_score = score
                        best_period = {
                            "tp": TP, "sl": SL, "mb": MB, "vf": vf,
                            "name": f"TP{TP}/SL{SL}/{MB}bar{' VF' if vf else ''}",
                            **r, "score": score
                        }
        
        # 也记录全局最佳
        if best_period and (best_global is None or best_period["score"] > best_global.get("score", -999)):
            best_global = best_period
    
    if best_period:
        bp = best_period
        print(f"  🏆 最佳: {bp['name']} | {bp['n']}笔 | 胜率{bp['wr']:.0f}% | 净{bp['tn']:+.2f}% | ${bp['usd']:+.2f} | 夏普{bp['sharpe']:.2f} | 盈亏比{bp['rr']:.2f}")
        # 打印每笔
        for t in sorted(bp["trades"], key=lambda x: x["in_dt"]):
            d = "多" if t["dir"]=="long" else "空"
            print(f"    {d} {t['in_dt'].strftime('%m-%d %H:%M')}→{t['out_dt'].strftime('%m-%d %H:%M')} 毛{t['gp']:+.2f}% 净{t['net']:+.2f}% {t['held']}根 {t['reason']}")

# ===== 全局最佳 =====
if best_global:
    bg = best_global
    print(f"\n{'='*120}")
    print(f"🌟 全局最佳策略")
    print(f"{'='*120}")
    print(f"参数: {bg['name']}")
    print(f"交易: {bg['n']}笔 | 胜率: {bg['wr']:.0f}% | 净盈亏: {bg['tn']:+.2f}%")
    print(f"$收益: {bg['usd']:+.2f} | 夏普: {bg['sharpe']:.2f} | 盈亏比: {bg['rr']:.2f}")
    print(f"\n逐笔明细:")
    for t in sorted(bg["trades"], key=lambda x: x["in_dt"]):
        d = "🔴多" if t["dir"]=="long" else "🟢空"
        print(f"  {d} {t['in_dt'].strftime('%m-%d %H:%M')} → {t['out_dt'].strftime('%m-%d %H:%M')} | "
              f"{t['gp']:+.3f}% → {t['net']:+.2f}% | {t['held']}根 | {t['reason']}")

# ===== 各周期汇总 =====
print(f"\n{'='*120}")
print(f"📊 各周期最优参数汇总")
print(f"{'='*120}")
print(f"{'周期':<8} {'最佳参数':<28} {'笔':>4} {'胜率':>7} {'净%':>9} {'$收益':>8} {'夏普':>6} {'盈亏比':>6}")
print(f"{'─'*85}")

for period_days in PERIODS:
    cutoff = now - timedelta(days=period_days)
    cutoff_ts = int(cutoff.timestamp() * 1000)
    subset = [b for b in bars if b["ts"] >= cutoff_ts]
    if not subset: continue
    
    best_period = None
    best_score = -999
    for TP in TP_OPTS:
        for SL in SL_OPTS:
            if SL >= TP: continue
            for MB in MAXB_OPTS:
                for vf in [True, False]:
                    r = run_backtest(subset, TP, SL, MB, vf)
                    if r["n"] == 0: continue
                    score = r["tn"] * 0.4 + r["sharpe"] * 0.3 + r["wr"] * 0.3
                    if score > best_score:
                        best_score = score
                        best_period = {"tp":TP, "sl":SL, "mb":MB, "vf":vf, **r}
    
    if best_period:
        bp = best_period
        vf_str = "VF" if bp["vf"] else ""
        print(f"{period_days:>4}天  TP{bp['tp']}/SL{bp['sl']}/{bp['mb']}b {vf_str:<3} {bp['n']:>4} {bp['w']}/{bp['n']}={bp['wr']:.0f}% {bp['tn']:>+9.2f} {bp['usd']:>+8.2f} {bp['sharpe']:>6.2f} {bp['rr']:>6.2f}")

print(f"\n数据: {len(bars)}根15分钟 | {bars[0]['dt'].strftime('%Y-%m-%d')}~{bars[-1]['dt'].strftime('%Y-%m-%d')} ({(bars[-1]['dt']-bars[0]['dt']).days}天)")
