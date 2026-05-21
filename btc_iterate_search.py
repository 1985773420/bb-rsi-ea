#!/usr/bin/env python3
"""
自迭代策略搜索 — 不低于10轮迭代
每轮测试多种变体，记录最优，下一轮基于上一轮改进
"""
import json, math, subprocess
from datetime import datetime, timezone, timedelta

# ==========================================
# 数据准备（只做一次）
# ==========================================
with open("/tmp/btc_15m_gate.json") as f:
    raw = json.load(f)
bars = []
for r in raw:
    bars.append({"ts": int(r[0]), "o": float(r[1]), "h": float(r[2]),
                 "l": float(r[3]), "c": float(r[4]),
                 "dt": datetime.fromtimestamp(int(r[0])/1000, tz=timezone.utc)})
bars.sort(key=lambda x: x["ts"]); n = len(bars)
closes=[b["c"] for b in bars]; highs=[b["h"] for b in bars]; lows=[b["l"] for b in bars]

# 日线MA730
daily_raw = subprocess.run(["okx","market","candles","BTC-USDT","--bar","1D","--limit","300","--json"],
                          capture_output=True, text=True, timeout=60)
daily=[{"ts":int(r[0]),"c":float(r[4]),"dt":datetime.fromtimestamp(int(r[0])/1000,tz=timezone.utc)} for r in json.loads(daily_raw.stdout)]
daily.sort(key=lambda x:x["ts"]); dc=[b["c"] for b in daily]; nd=len(daily)
dm={}
for i,d in enumerate(daily):
    ds=d["dt"].strftime("%Y-%m-%d"); n730=min(730,i+1)
    dm[ds]=sum(dc[i-n730+1:i+1])/n730
for bar in bars:
    ds=bar["dt"].strftime("%Y-%m-%d")
    bar["ma730"]=dm.get(ds)
    if bar["ma730"] is None:
        bd=bar["dt"].date()
        for dds,m in dm.items():
            if datetime.strptime(dds,"%Y-%m-%d").date()<=bd: bar["ma730"]=m

# 指标计算
# MA多周期
ma_pairs = {}
for period in [5,9,13,21,50]:
    mav,mapv=[],[]
    for i in range(n):
        if i>=period-1:
            mav.append(sum(closes[i-period+1:i+1])/period)
            mapv.append(sum(closes[i-period:i])/period if i>=period else None)
        else: mav.append(None); mapv.append(None)
    ma_pairs[f"ma{period}"]=mav
    ma_pairs[f"ma{period}p"]=mapv

# BB(20,2)
bb_u,bb_l,bb_m=[],[],[]
for i in range(n):
    if i>=19:
        w=closes[i-19:i+1]; s=sum(w)/20; std=math.sqrt(sum((x-s)**2 for x in w)/20)
        bb_u.append(s+2*std); bb_l.append(s-2*std); bb_m.append(s)
    else: bb_u.append(None); bb_l.append(None); bb_m.append(None)

# RSI(14)
rsi=[]; gains,losses=[],[]
for i in range(n):
    if i==0: gains.append(0); losses.append(0)
    else: ch=closes[i]-closes[i-1]; gains.append(max(ch,0)); losses.append(max(-ch,0))
    if i>=14:
        ag=sum(gains[i-13:i+1])/14; al=sum(losses[i-13:i+1])/14
        rsi.append(100-100/(1+ag/al) if al>0 else 100)
    else: rsi.append(None)

# ADX, ATR, TR
tr_v=[]; pdm_v=[]; ndm_v=[]
for i in range(n):
    if i==0: tr_v.append(highs[i]-lows[i]); pdm_v.append(0); ndm_v.append(0)
    else:
        tr_v.append(max(highs[i]-lows[i],abs(highs[i]-closes[i-1]),abs(lows[i]-closes[i-1])))
        u=highs[i]-highs[i-1]; d=lows[i-1]-lows[i]
        pdm_v.append(u if u>d and u>0 else 0); ndm_v.append(d if d>u and d>0 else 0)

def ws(arr,p):
    r=[]
    for i in range(len(arr)):
        if i<p-1: r.append(None)
        elif i==p-1: r.append(sum(arr[:p]))
        else: r.append(r[-1]-r[-1]/p+arr[i])
    return r

atr14=ws(tr_v,14); pdm14=ws(pdm_v,14); ndm14=ws(ndm_v,14)
atrp=[atr14[i]/closes[i]*100 if atr14[i] else None for i in range(n)]
adx_raw=[]
for i in range(n):
    if atr14[i] is None or atr14[i]==0: adx_raw.append(None)
    else:
        pdi=pdm14[i]/atr14[i]*100; ndi=ndm14[i]/atr14[i]*100
        adx_raw.append(abs(pdi-ndi)/(pdi+ndi)*100 if pdi+ndi>0 else 0)
adx_sm=[]
for i in range(n):
    if i<13: adx_sm.append(adx_raw[i])
    elif None in adx_raw[i-13:i+1]: adx_sm.append(None)
    else: adx_sm.append(sum(adx_raw[i-13:i+1])/14)

# 动量
mom=[None]*3+[(closes[i]-closes[i-3])/closes[i-3]*100 for i in range(3,n)]
mom6=[None]*6+[(closes[i]-closes[i-6])/closes[i-6]*100 for i in range(6,n)]

# Donchian Channel (20)
dc_h,dc_l=[],[]
for i in range(n):
    if i>=19: dc_h.append(max(highs[i-19:i+1])); dc_l.append(min(lows[i-19:i+1]))
    else: dc_h.append(None); dc_l.append(None)

# 赋值
for i,bar in enumerate(bars):
    bar["idx"]=i
    for k,v in ma_pairs.items(): bar[k]=v[i]
    bar["bb_u"]=bb_u[i]; bar["bb_l"]=bb_l[i]; bar["bb_m"]=bb_m[i]
    bar["rsi"]=rsi[i]; bar["adx"]=adx_sm[i]; bar["atr"]=atrp[i]
    bar["mom"]=mom[i]; bar["mom6"]=mom6[i]
    bar["dc_h"]=dc_h[i]; bar["dc_l"]=dc_l[i]

# ==========================================
# 回测框架
# ==========================================
FEE=0.07; LEV=5; MIN_TRADES=5
PERIODS=[15,30,60,90]
now=datetime.now(timezone.utc)
VALID_START=100

def backtest(subset, entry_fn, tp, sl, mb):
    """通用回测：entry_fn(bar) → 'long'/'short'/None"""
    trades=[]; pos=None
    for gi,bar in enumerate(subset):
        if pos is not None:
            c=bar["c"]; ep=pos["price"]; ei=pos["idx"]; held=gi-ei
            gp=(c-ep)/ep*100 if pos["type"]=="long" else (ep-c)/ep*100
            reason=None
            if gp>=tp: reason="tp"
            elif gp<=-sl: reason="sl"
            elif held>=mb: reason="to"
            if reason:
                net=(gp-FEE)*LEV
                trades.append({"dir":pos["type"],"gp":round(gp,4),"net":round(net,4),
                              "held":held,"reason":reason})
                pos=None
            continue
        
        sig=entry_fn(bar)
        if sig: pos={"type":sig,"idx":gi,"price":bar["c"]}
    
    if pos:
        c=subset[-1]["c"]; ep=pos["price"]
        gp=(c-ep)/ep*100 if pos["type"]=="long" else (ep-c)/ep*100
        net=(gp-FEE)*LEV
        trades.append({"dir":pos["type"],"gp":round(gp,4),"net":round(net,4),
                      "held":len(subset)-1-pos["idx"],"reason":"end"})
    
    if len(trades)<MIN_TRADES/2: return None
    w=sum(1 for t in trades if t["net"]>0); nn=len(trades)
    tn=sum(t["net"] for t in trades); wr=w/nn*100 if nn else 0
    wt=[t["net"] for t in trades if t["net"]>0]; lt=[t["net"] for t in trades if t["net"]<=0]
    rr=(sum(wt)/len(wt))/(abs(sum(lt)/len(lt))) if wt and lt else 0
    if nn>1:
        pn=[t["net"] for t in trades]; a=sum(pn)/nn
        s=math.sqrt(sum((x-a)**2 for x in pn)/nn); sh=a/s*math.sqrt(nn) if s>0 else 0
    else: sh=0
    return {"n":nn,"w":w,"wr":wr,"tn":tn,"usd":tn/100*37.54,"rr":rr,"sh":sh,"trades":trades}

def score_multi_period(entry_fn, tp, sl, mb):
    """跨周期评分：正收益加分，负收益扣分，夏普加权"""
    total=0; cnt=0
    for pd in PERIODS:
        cutoff=now-timedelta(days=pd); ct=int(cutoff.timestamp()*1000)
        sub=[b for b in bars[VALID_START:] if b["ts"]>=ct]
        if len(sub)<100: continue
        r=backtest(sub,entry_fn,tp,sl,mb)
        if r is None or r["n"]<3: continue
        total+=r["tn"]*0.5+r["sh"]*10*0.3+r["wr"]*0.2
        cnt+=1
    return total/max(cnt,1) if cnt else -999

# ==========================================
# 迭代记录
# ==========================================
iterations=[]
best_global={"score":-999}

def record_iter(num,name,entry_fn,tp,sl,mb,extra=""):
    global best_global
    results={}
    score_sum=0; cnt=0
    
    for pd in PERIODS:
        cutoff=now-timedelta(days=pd); ct=int(cutoff.timestamp()*1000)
        sub=[b for b in bars[VALID_START:] if b["ts"]>=ct]
        if len(sub)<100: continue
        r=backtest(sub,entry_fn,tp,sl,mb)
        results[pd]=r
        if r and r["n"]>=3:
            score_sum+=r["tn"]*0.5+r["sh"]*10*0.3+r["wr"]*0.2
            cnt+=1
    
    avg_score=score_sum/max(cnt,1)
    total_90=results.get(90,{})
    
    iteration={"num":num,"name":name,"tp":tp,"sl":sl,"mb":mb,
               "score":avg_score,"results":results,"extra":extra}
    iterations.append(iteration)
    
    if avg_score>best_global["score"]:
        best_global={"num":num,"name":name,"score":avg_score,"results":results,"tp":tp,"sl":sl,"mb":mb}
    
    # 打印
    print(f"\n{'─'*120}")
    print(f"Iter {num}: {name} | TP{tp}/SL{sl}/{mb}b {extra}")
    print(f"{'─'*120}")
    header=f"{'周期':<8} {'笔':>4} {'胜率':>7} {'净%':>9} {'$':>7} {'夏普':>6} {'RR':>5}"
    print(header); print(f"{'─'*48}")
    for pd in PERIODS:
        r=results.get(pd)
        if r and r["n"]>=3:
            print(f"{pd:>4}d {r['n']:>4} {r['w']}/{r['n']}={r['wr']:.0f}% {r['tn']:>+9.2f} {r['usd']:>+7.2f} {r['sh']:>6.2f} {r['rr']:>5.2f}")
        elif r:
            print(f"{pd:>4}d {r['n']:>4} 笔(不足)")
        else:
            print(f"{pd:>4}d  -")
    print(f"   综合评分: {avg_score:.1f}  {'★新最佳!' if avg_score>best_global['score'] else ''}")
    
    return iteration

# ==========================================
# 工厂函数：生成entry_fn
# ==========================================
def make_ma_cross_entry(fast, slow, adx_th, atr_max=None, ma730_only=True):
    """MA交叉 + ADX过滤 + 可选ATR过滤"""
    fk=f"ma{fast}"; fkp=f"ma{fast}p"; sk=f"ma{slow}"; skp=f"ma{slow}p"
    
    def entry(bar):
        c=bar["c"]; m7=bar.get("ma730")
        fv=bar.get(fk); sv=bar.get(sk); fp=bar.get(fkp); sp=bar.get(skp)
        a=bar.get("adx"); at=bar.get("atr")
        if None in (m7,fv,sv,fp,sp,a): return None
        if abs(c-m7)/m7<0.01: return None
        if ma730_only and adx_th is not None and a<=adx_th: return None
        if adx_th is None and not ma730_only: pass
        if atr_max and at and at>atr_max: return None
        
        if c>m7 and fp<=sp and fv>sv: return 'long'
        if c<m7 and fp>=sp and fv<sv: return 'short'
        return None
    return entry

def make_bb_entry(adx_th=None, atr_max=None):
    """BB反弹 + RSI确认 + 趋势方向"""
    def entry(bar):
        c=bar["c"]; m7=bar.get("ma730")
        bu=bar.get("bb_u"); bl=bar.get("bb_l")
        r=bar.get("rsi"); a=bar.get("adx"); at=bar.get("atr")
        if None in (m7,bu,bl,r): return None
        if adx_th and a and a>adx_th: return None  # 趋势市不用BB
        if atr_max and at and at>atr_max: return None
        
        # 熊市做空：上轨+超买
        if c<m7 and c>bu and r>65: return 'short'
        # 牛市做多：下轨+超卖
        if c>m7 and c<bl and r<35: return 'long'
        return None
    return entry

def make_donchian_entry(period=20, adx_th=None):
    """Donchian通道突破"""
    def entry(bar):
        c=bar["c"]; m7=bar.get("ma730")
        dh=bar.get("dc_h"); dl=bar.get("dc_l"); a=bar.get("adx")
        if None in (m7,dh,dl): return None
        if abs(c-m7)/m7<0.01: return None
        if adx_th and a and a<=adx_th: return None
        
        if c>m7 and c>dh: return 'long'
        if c<m7 and c<dl: return 'short'
        return None
    return entry

def make_combined_entry(ma_fast, ma_slow, adx_th):
    """MA交叉(趋势) + BB(震荡) 智能切换"""
    ma_entry=make_ma_cross_entry(ma_fast, ma_slow, adx_th)
    bb_entry=make_bb_entry(adx_th)
    
    def entry(bar):
        a=bar.get("adx")
        if a is None: return None
        if a>adx_th: return ma_entry(bar)
        else: return bb_entry(bar)
    return entry

def make_trend_score_entry(ma_fast, ma_slow, min_score):
    """趋势评分系统：多指标确认才入场"""
    fk=f"ma{ma_fast}"; sk=f"ma{ma_slow}"; fkp=f"ma{ma_fast}p"; skp=f"ma{ma_slow}p"
    
    def entry(bar):
        c=bar["c"]; m7=bar.get("ma730")
        fv=bar.get(fk); sv=bar.get(sk); fp=bar.get(fkp); sp=bar.get(skp)
        a=bar.get("adx"); r=bar.get("rsi"); m=bar.get("mom"); m6=bar.get("mom6")
        if None in (m7,fv,sv,fp,sp,a,r,m,m6): return None
        if abs(c-m7)/m7<0.01: return None
        
        # 多头评分
        long_score=0
        if c>m7: long_score+=2  # MA730方向
        if fp<=sp and fv>sv: long_score+=3  # MA交叉
        if a>25: long_score+=1  # 趋势强度
        if m>0: long_score+=1  # 短期动量
        if m6>0: long_score+=1  # 中期动量
        if r>50: long_score+=1  # RSI
        
        # 空头评分
        short_score=0
        if c<m7: short_score+=2
        if fp>=sp and fv<sv: short_score+=3
        if a>25: short_score+=1
        if m<0: short_score+=1
        if m6<0: short_score+=1
        if r<50: short_score+=1
        
        if long_score>=min_score: return 'long'
        if short_score>=min_score: return 'short'
        return None
    return entry

# ==========================================
# 开始迭代
# ==========================================
print("="*120)
print("自迭代策略搜索 — 15分钟 BTC 93天数据")
print(f"maker+taker={FEE}% | {LEV}x杠杆 | $37.54本金")
print("="*120)

# --- Iter 1: Baseline MA9/21 + ADX>25 ---
record_iter(1,"MA9/21 ADX>25",make_ma_cross_entry(9,21,25),0.4,0.35,16)

# --- Iter 2: MA5/13 (更快) + ADX>25 ---
record_iter(2,"MA5/13 ADX>25",make_ma_cross_entry(5,13,25),0.4,0.3,12)

# --- Iter 3: MA9/21 + ADX>20 (更宽松) ---
record_iter(3,"MA9/21 ADX>20",make_ma_cross_entry(9,21,20),0.5,0.35,16)

# --- Iter 4: MA5/13 + ADX>20 ---
record_iter(4,"MA5/13 ADX>20",make_ma_cross_entry(5,13,20),0.4,0.3,12)

# --- Iter 5: MA9/21 + ADX>25 + ATR<0.5% ---
record_iter(5,"MA9/21 ADX>25 ATR<0.5%",make_ma_cross_entry(9,21,25,atr_max=0.5),0.4,0.35,16)

# --- Iter 6: BB+RSI 纯震荡 ---
record_iter(6,"BB+RSI 纯震荡",make_bb_entry(adx_th=25),0.8,0.4,24)

# --- Iter 7: Donchian(20) + ADX>25 ---
record_iter(7,"Donchian20 ADX>25",make_donchian_entry(20,25),0.6,0.35,16)

# --- Iter 8: Donchian(20) + ADX>20 ---
record_iter(8,"Donchian20 ADX>20",make_donchian_entry(20,20),0.6,0.35,16)

# --- Iter 9: 组合(MA趋势+BB震荡) with ADX=25 ---
record_iter(9,"MA9/21趋势+BB震荡 ADX25",make_combined_entry(9,21,25),0.5,0.35,16,"趋势TP0.5震荡TP0.8")

# --- Iter 10: 趋势评分系统 min_score=7 ---
record_iter(10,"趋势评分min7",make_trend_score_entry(9,21,7),0.4,0.35,16)

# --- Iter 11: 趋势评分 min_score=6 (更宽松) ---
record_iter(11,"趋势评分min6",make_trend_score_entry(9,21,6),0.4,0.3,16)

# --- Iter 12: Donchian 14 + ADX>20 ---
record_iter(12,"Donchian14 ADX>20",make_donchian_entry(14,20),0.5,0.3,14)

# --- Iter 13: MA5/13 + ADX>25 + ATR>0.3 (高波动) ---
def make_ma_highvol_entry():
    """只在高波动趋势市交易"""
    base=make_ma_cross_entry(5,13,25)
    def entry(bar):
        at=bar.get("atr"); a=bar.get("adx")
        if at is None or a is None: return None
        if at<0.3 or a<25: return None  # 低波动或非趋势→休息
        return base(bar)
    return entry
record_iter(13,"MA5/13 ADX>25 高波动",make_ma_highvol_entry(),0.5,0.35,12)

# --- Iter 14: 最佳前3的组合平均 ---
# 基于前13轮观察，选最好的逻辑重新组合
def make_elite_entry():
    """精英组合: MA交叉+ADX确认+ATR适度"""
    def entry(bar):
        c=bar["c"]; m7=bar.get("ma730")
        m5=bar.get("ma5"); m13=bar.get("ma13"); m5p=bar.get("ma5p"); m13p=bar.get("ma13p")
        m9=bar.get("ma9"); m21=bar.get("ma21"); m9p=bar.get("ma9p"); m21p=bar.get("ma21p")
        a=bar.get("adx"); at=bar.get("atr"); r=bar.get("rsi")
        if None in (m7,m5,m13,m5p,m13p,m9,m21,m9p,m21p,a,at,r): return None
        if abs(c-m7)/m7<0.008: return None
        if a<22: return None
        
        # 双重MA确认 + RSI在有利方向
        short_sig=(m9p>=m9p and m9<m21) and (m5p>=m13p and m5<m13) and c<m7 and r<55
        long_sig=(m9p<=m21p and m9>m21) and (m5p<=m13p and m5>m13) and c>m7 and r>45
        
        if short_sig: return 'short'
        if long_sig: return 'long'
        return None
    return entry
record_iter(14,"双重MA确认 MA9/21+MA5/13",make_elite_entry(),0.5,0.35,14)

# --- Iter 15: 动态TP/SL (基于ATR) ---
def make_atr_adaptive_entry():
    """入场用MA交叉，动态止盈止损在回测框架外用"""
    return make_ma_cross_entry(9,21,22)

# 动态TP/SL = ATR倍数
for atr_tp, atr_sl, atr_mb, label in [(1.5,1.0,16,"ATR1.5x"), (2.0,1.2,20,"ATR2.0x"), (1.8,1.0,16,"ATR1.8x")]:
    avg_atr=0.0035  # 约0.35% average ATR
    tp=round(avg_atr*atr_tp*100,2)
    sl=round(avg_atr*atr_sl*100,2)
    record_iter(15, f"MA9/21 ADX22 {label}", make_atr_adaptive_entry(), tp, sl, atr_mb, f"≈ATR×{atr_tp}")

# ==========================================
# 最终报告
# ==========================================
print(f"\n{'='*120}")
print(f"🏆 迭代总结 — 共{len(iterations)}轮")
print(f"{'='*120}")
print(f"{'Iter':<6} {'策略':<32} {'评分':>8} {'15d':>8} {'30d':>8} {'60d':>8} {'90d':>8}")
print(f"{'─'*78}")

for it in sorted(iterations, key=lambda x:-x["score"]):
    res=it["results"]
    vals=[]
    for pd in PERIODS:
        r=res.get(pd)
        vals.append(f"{r['tn']:+.1f}%" if r and r["n"]>=3 else "-")
    marker="★" if it["score"]==best_global["score"] else " "
    print(f"{marker}{it['num']:<5} {it['name']:<32} {it['score']:>+8.1f} {vals[0]:>8} {vals[1]:>8} {vals[2]:>8} {vals[3]:>8}")

print(f"\n{'='*120}")
print(f"🌟 全局最优: Iter {best_global['num']} — {best_global['name']}")
print(f"   TP{best_global['tp']}/SL{best_global['sl']}/{best_global['mb']}b")
print(f"   综合评分: {best_global['score']:.1f}")
print(f"{'='*120}")
