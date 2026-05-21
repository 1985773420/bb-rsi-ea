#!/usr/bin/env python3
"""
BTC 15分钟 Bollinger Band + RSI + MA730方向 全周期回测
策略: BB下轨+RSI超卖+MA730之下=做空反弹 / BB上轨+RSI超买+MA730之上=做多回调
"""
import json, math
from datetime import datetime, timezone, timedelta

# ===== 加载数据 =====
with open("/tmp/btc_15m_gate.json") as f:
    raw = json.load(f)

bars = []
for r in raw:
    bars.append({
        "ts": int(r[0]), "o": float(r[1]), "h": float(r[2]),
        "l": float(r[3]), "c": float(r[4]), "v": float(r[5]),
        "dt": datetime.fromtimestamp(int(r[0])/1000, tz=timezone.utc)
    })
bars.sort(key=lambda x: x["ts"])

# ===== 日线MA =====
import subprocess
def okx_cmd(args):
    r = subprocess.run(["okx"] + args, capture_output=True, text=True, timeout=60)
    return json.loads(r.stdout)

print("拉取日线MA...")
daily_raw = okx_cmd(["market", "candles", "BTC-USDT", "--bar", "1D", "--limit", "300", "--json"])
daily = []
for r in daily_raw:
    daily.append({
        "ts": int(r[0]), "c": float(r[4]),
        "dt": datetime.fromtimestamp(int(r[0])/1000, tz=timezone.utc)
    })
daily.sort(key=lambda x: x["ts"]); nd = len(daily)
dc = [b["c"] for b in daily]
daily_ma = {}
for i, d in enumerate(daily):
    ds = d["dt"].strftime("%Y-%m-%d")
    n730 = min(730, i+1)
    ma730 = sum(dc[i-n730+1:i+1]) / n730
    daily_ma[ds] = ma730

# 匹配MA730到15min bar
for bar in bars:
    ds = bar["dt"].strftime("%Y-%m-%d")
    if ds in daily_ma:
        bar["ma730"] = daily_ma[ds]
    else:
        bd = bar["dt"].date()
        best = None
        for dds, m in daily_ma.items():
            if datetime.strptime(dds, "%Y-%m-%d").date() <= bd:
                best = m
        bar["ma730"] = best

# ===== 计算指标 =====
# Bollinger Bands (20, 2), RSI(14), ATR(14)
closes = [b["c"] for b in bars]
highs = [b["h"] for b in bars]
lows = [b["l"] for b in bars]

# BB
sma20, bb_upper, bb_lower, bb_mid = [], [], [], []
for i in range(len(closes)):
    if i >= 19:
        w = closes[i-19:i+1]
        sma = sum(w)/20
        std = math.sqrt(sum((x-sma)**2 for x in w)/20)
        sma20.append(sma)
        bb_upper.append(sma + 2*std)
        bb_lower.append(sma - 2*std)
        bb_mid.append(sma)
    else:
        sma20.append(None); bb_upper.append(None); bb_lower.append(None); bb_mid.append(None)

# RSI(14)
rsi = []
gains, losses = [], []
for i in range(len(closes)):
    if i == 0: gains.append(0); losses.append(0)
    else:
        ch = closes[i] - closes[i-1]
        gains.append(max(ch, 0)); losses.append(max(-ch, 0))
    if i >= 14:
        avg_g = sum(gains[i-13:i+1])/14
        avg_l = sum(losses[i-13:i+1])/14
        if avg_l == 0: rsi.append(100)
        else: rsi.append(100 - 100/(1 + avg_g/avg_l))
    else:
        rsi.append(None)

# ATR(14)
tr = []
for i in range(len(closes)):
    if i==0: tr.append(highs[i]-lows[i])
    else: tr.append(max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])))
atr = [sum(tr[max(0,i-13):i+1])/min(i+1,14) for i in range(len(closes))]

for i, bar in enumerate(bars):
    bar["bb_u"] = bb_upper[i]; bar["bb_l"] = bb_lower[i]; bar["bb_m"] = bb_mid[i]
    bar["rsi"] = rsi[i]; bar["atr"] = atr[i]

# ===== 回测 =====
FEE = 0.07; LEV = 5
PERIODS = [15, 30, 60, 90]
now = datetime.now(timezone.utc)

# 策略参数: BB触碰+RSI确认+MA730过滤
# SHORT: close > bb_u AND rsi > RSI_HIGH AND close < ma730 → 做空反弹
# LONG: close < bb_l AND rsi < RSI_LOW AND close > ma730 → 做多回调
# TP: 价格回到 mid-band 或 fixed TP%
# SL: fixed SL% of price

RSI_HIGH = 65
RSI_LOW = 35

param_sets = [
    # (TP%, SL%, max_bars, name)
    (0.30, 0.20, 12, "TP0.3/SL0.2/12b"),
    (0.40, 0.25, 14, "TP0.4/SL0.25/14b"),
    (0.50, 0.30, 16, "TP0.5/SL0.3/16b"),
    (0.60, 0.35, 20, "TP0.6/SL0.35/20b"),
    (0.80, 0.40, 24, "TP0.8/SL0.4/24b"),
]

def run_bb_backtest(subset, TP, SL, MAX_BARS):
    trades = []; pos = None
    
    for gi, bar in enumerate(subset):
        c = bar["c"]; m7 = bar.get("ma730")
        bu = bar.get("bb_u"); bl = bar.get("bb_l"); bm = bar.get("bb_m")
        r = bar.get("rsi"); a = bar.get("atr")
        
        if None in (m7, bu, bl, bm, r, a): continue
        
        short_sig = c > bu and r > RSI_HIGH and c < m7  # 上轨+超买+熊市→做空
        long_sig = c < bl and r < RSI_LOW and c > m7    # 下轨+超卖+牛市→做多
        
        if pos is not None:
            ep = pos["price"]; ei = pos["idx"]; held = gi - ei
            gp = (c-ep)/ep*100 if pos["type"]=="long" else (ep-c)/ep*100
            
            reason = None
            if gp >= TP: reason = "tp"
            elif gp <= -SL: reason = "sl"
            elif pos["type"]=="long" and c >= bm: reason = "mid"  # 回到中轨止盈
            elif pos["type"]=="short" and c <= bm: reason = "mid"
            elif held >= MAX_BARS: reason = "timeout"
            
            if reason:
                net = (gp - FEE) * LEV
                trades.append({
                    "dir": pos["type"], "gp": round(gp,4), "net": round(net,4),
                    "held": held, "reason": reason,
                    "in_dt": subset[ei]["dt"], "out_dt": bar["dt"]
                })
                pos = None
            continue
        
        if short_sig:
            pos = {"type": "short", "idx": gi, "price": c}
        elif long_sig:
            pos = {"type": "long", "idx": gi, "price": c}
    
    if pos:
        lb = subset[-1]; c = lb["c"]; ep = pos["price"]
        gp = (c-ep)/ep*100 if pos["type"]=="long" else (ep-c)/ep*100
        held = len(subset)-1-pos["idx"]
        net = (gp - FEE) * LEV
        trades.append({
            "dir": pos["type"], "gp": round(gp,4), "net": round(net,4),
            "held": held, "reason": "end",
            "in_dt": subset[pos["idx"]]["dt"], "out_dt": lb["dt"]
        })
    
    w = sum(1 for t in trades if t["net"] > 0)
    n = len(trades)
    tn = sum(t["net"] for t in trades)
    usd = tn/100*37.54
    wr = w/n*100 if n else 0
    
    wt = [t["net"] for t in trades if t["net"]>0]
    lt = [t["net"] for t in trades if t["net"]<=0]
    rr = (sum(wt)/len(wt))/(abs(sum(lt)/len(lt))) if wt and lt else 0
    
    if n > 1:
        pn = [t["net"] for t in trades]
        a = sum(pn)/n; s = math.sqrt(sum((x-a)**2 for x in pn)/n)
        sh = a/s*math.sqrt(n) if s>0 else 0
    else: sh = 0
    
    return {"n":n,"w":w,"wr":wr,"tn":tn,"usd":usd,"rr":rr,"sharpe":sh,"trades":trades}

# ===== 遍历 =====
print(f"\n{'='*115}")
print(f"BTC 15分钟 BB(20,2) + RSI(14, {RSI_LOW}/{RSI_HIGH}) + MA730方向过滤")
print(f"逻辑: 下轨+超卖+牛市=做多 | 上轨+超买+熊市=做空 | 回到中轨=止盈")
print(f"maker(0.02%)+taker(0.05%)={FEE}% | {LEV}x | $37.54")
print(f"{'='*115}")

for period_days in PERIODS:
    cutoff = now - timedelta(days=period_days)
    cutoff_ts = int(cutoff.timestamp() * 1000)
    subset = [b for b in bars if b["ts"] >= cutoff_ts]
    if len(subset) < 50: continue
    
    days_actual = (subset[-1]["dt"] - subset[0]["dt"]).days
    print(f"\n{'─'*115}")
    print(f"📅 {period_days}天 ({subset[0]['dt'].strftime('%m-%d')}~{subset[-1]['dt'].strftime('%m-%d')}, {len(subset)}根)")
    print(f"{'─'*115}")
    
    best = None; best_score = -999
    
    for TP, SL, MB, name in param_sets:
        r = run_bb_backtest(subset, TP, SL, MB)
        if r["n"] == 0: continue
        score = r["tn"]*0.4 + r["sharpe"]*0.3 + r["wr"]*0.3
        if score > best_score:
            best_score = score
            best = {"tp":TP, "sl":SL, "mb":MB, "name":name, **r}
        # 打印每个参数组合
        print(f"  {name:<18} {r['n']:>4}笔 胜{r['w']}/{r['n']}={r['wr']:.0f}%  净{r['tn']:>+8.2f}%  ${r['usd']:>+7.2f}  夏普{r['sharpe']:>6.2f}  盈亏比{r['rr']:.2f}")
    
    if best and best["n"]:
        print(f"\n  🏆 最佳: {best['name']} | {best['n']}笔 | 胜{best['wr']:.0f}% | 净{best['tn']:+.2f}% | ${best['usd']:+.2f}")
        # 打印前10笔 + 统计多空
        longs = [t for t in best["trades"] if t["dir"]=="long"]
        shorts = [t for t in best["trades"] if t["dir"]=="short"]
        if longs:
            lw = sum(1 for t in longs if t["net"]>0)
            print(f"    多头: {len(longs)}笔 胜{lw}/{len(longs)}={lw/len(longs)*100:.0f}% 盈亏{sum(t['net'] for t in longs):+.2f}%")
        if shorts:
            sw = sum(1 for t in shorts if t["net"]>0)
            print(f"    空头: {len(shorts)}笔 胜{sw}/{len(shorts)}={sw/len(shorts)*100:.0f}% 盈亏{sum(t['net'] for t in shorts):+.2f}%")

# ===== 汇总 =====
print(f"\n{'='*115}")
print(f"📊 各周期最优参数汇总")
print(f"{'='*115}")
print(f"{'周期':<8} {'最佳参数':<22} {'笔':>4} {'胜率':>7} {'净%':>9} {'$收益':>8} {'夏普':>6} {'盈亏比':>6}")
print(f"{'─'*80}")

for period_days in PERIODS:
    cutoff = now - timedelta(days=period_days)
    cutoff_ts = int(cutoff.timestamp() * 1000)
    subset = [b for b in bars if b["ts"] >= cutoff_ts]
    if len(subset) < 50: continue
    
    best = None; best_score = -999
    for TP, SL, MB, name in param_sets:
        r = run_bb_backtest(subset, TP, SL, MB)
        if r["n"] == 0: continue
        score = r["tn"]*0.4 + r["sharpe"]*0.3 + r["wr"]*0.3
        if score > best_score:
            best_score = score
            best = {"tp":TP, "sl":SL, "mb":MB, "name":name, **r}
    
    if best:
        print(f"{period_days:>4}天  {best['name']:<22} {best['n']:>4} {best['w']}/{best['n']}={best['wr']:.0f}% {best['tn']:>+9.2f} {best['usd']:>+8.2f} {best['sharpe']:>6.2f} {best['rr']:>6.2f}")

print(f"\n数据: {len(bars)}根 | {bars[0]['dt'].strftime('%Y-%m-%d')}~{bars[-1]['dt'].strftime('%Y-%m-%d')} ({(bars[-1]['dt']-bars[0]['dt']).days}天)")
print(f"{'='*115}")
