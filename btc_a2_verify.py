#!/usr/bin/env python3
"""
最优组合: MA9/21交叉 + MA730方向 + ADX>25趋势过滤
参数: TP0.4/SL0.35/16b
"""
import json, math, subprocess
from datetime import datetime, timezone, timedelta

# 数据
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
daily.sort(key=lambda x:x["ts"]); dc=[b["c"] for b in daily]
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

# MA9/21
ma9,ma21,ma9p,ma21p=[],[],[],[]
for i in range(n):
    if i>=8: ma9.append(sum(closes[i-8:i+1])/9); ma9p.append(sum(closes[i-9:i])/9 if i>=9 else None)
    else: ma9.append(None); ma9p.append(None)
    if i>=20: ma21.append(sum(closes[i-20:i+1])/21); ma21p.append(sum(closes[i-21:i])/21 if i>=21 else None)
    else: ma21.append(None); ma21p.append(None)

# ADX(14)
tr=[]; pd=[]; nd=[]
for i in range(n):
    if i==0: tr.append(highs[i]-lows[i]); pd.append(0); nd.append(0)
    else:
        tr.append(max(highs[i]-lows[i],abs(highs[i]-closes[i-1]),abs(lows[i]-closes[i-1])))
        u=highs[i]-highs[i-1]; d=lows[i-1]-lows[i]
        pd.append(u if u>d and u>0 else 0); nd.append(d if d>u and d>0 else 0)
def ws(arr,p):
    r=[]
    for i in range(len(arr)):
        if i<p-1: r.append(None)
        elif i==p-1: r.append(sum(arr[:p]))
        else: r.append(r[-1]-r[-1]/p+arr[i])
    return r
atr=ws(tr,14); pdm=ws(pd,14); ndm=ws(nd,14)
adx=[]
for i in range(n):
    if atr[i] is None or atr[i]==0: adx.append(None)
    else:
        pdi=pdm[i]/atr[i]*100; ndi=ndm[i]/atr[i]*100
        adx.append(abs(pdi-ndi)/(pdi+ndi)*100 if pdi+ndi>0 else 0)
adx_sm=[]
for i in range(n):
    if i<13: adx_sm.append(adx[i])
    elif None in adx[i-13:i+1]: adx_sm.append(None)
    else: adx_sm.append(sum(adx[i-13:i+1])/14)

for i,bar in enumerate(bars):
    bar["ma9"]=ma9[i]; bar["ma21"]=ma21[i]; bar["ma9p"]=ma9p[i]; bar["ma21p"]=ma21p[i]
    bar["adx"]=adx_sm[i]

# ===== 回测 =====
FEE=0.07; LEV=5; ADX_TH=25; TP=0.4; SL=0.35; MB=16
PERIODS=[15,30,60,90]
now=datetime.now(timezone.utc)

def run(subset):
    trades=[]; pos=None
    for gi,bar in enumerate(subset):
        c=bar["c"]; m7=bar.get("ma730")
        m9=bar.get("ma9"); m21=bar.get("ma21"); m9p=bar.get("ma9p"); m21p=bar.get("ma21p")
        a=bar.get("adx")
        if None in (m7,m9,m21,m9p,m21p,a): continue
        
        tu=c>m7; td=c<m7; nm=abs(c-m7)/m7<0.01
        gc=m9p<=m21p and m9>m21; dc=m9p>=m21p and m9<m21
        trend=a>ADX_TH
        
        if pos is not None:
            ep=pos["price"]; ei=pos["idx"]; held=gi-ei
            gp=(c-ep)/ep*100 if pos["type"]=="long" else (ep-c)/ep*100
            reason=None
            if gp>=TP: reason="tp"
            elif gp<=-SL: reason="sl"
            elif held>=MB: reason="to"
            if reason:
                net=(gp-FEE)*LEV
                trades.append({"dir":pos["type"],"gp":round(gp,4),"net":round(net,4),
                              "held":held,"reason":reason,"in_dt":subset[ei]["dt"],"out_dt":bar["dt"]})
                pos=None
            continue
        
        if nm or not trend: continue
        if tu and gc: pos={"type":"long","idx":gi,"price":c}
        elif td and dc: pos={"type":"short","idx":gi,"price":c}
    
    if pos:
        lb=subset[-1]; c=lb["c"]; ep=pos["price"]
        gp=(c-ep)/ep*100 if pos["type"]=="long" else (ep-c)/ep*100
        net=(gp-FEE)*LEV
        trades.append({"dir":pos["type"],"gp":round(gp,4),"net":round(net,4),
                      "held":len(subset)-1-pos["idx"],"reason":"end","in_dt":subset[pos["idx"]]["dt"],"out_dt":lb["dt"]})
    
    w=sum(1 for t in trades if t["net"]>0); nn=len(trades)
    tn=sum(t["net"] for t in trades)
    usd=tn/100*37.54; wr=w/nn*100 if nn else 0
    wt=[t["net"] for t in trades if t["net"]>0]; lt=[t["net"] for t in trades if t["net"]<=0]
    rr=(sum(wt)/len(wt))/(abs(sum(lt)/len(lt))) if wt and lt else 0
    if nn>1:
        pn=[t["net"] for t in trades]; a=sum(pn)/nn
        s=math.sqrt(sum((x-a)**2 for x in pn)/nn); sh=a/s*math.sqrt(nn) if s>0 else 0
    else: sh=0
    return {"n":nn,"w":w,"wr":wr,"tn":tn,"usd":usd,"rr":rr,"sh":sh,"trades":trades}

print(f"\n{'='*110}")
print(f"最优策略: MA9/21交叉 + MA730方向 + ADX>{ADX_TH}趋势过滤")
print(f"TP{TP}/SL{SL}/{MB}b | maker+taker={FEE}% | {LEV}x | $37.54")
print(f"{'='*110}")

for pd in PERIODS:
    cutoff=now-timedelta(days=pd)
    ct=int(cutoff.timestamp()*1000)
    sub=[b for b in bars if b["ts"]>=ct]
    if len(sub)<100: continue
    
    adx_v=[b.get("adx") for b in sub if b.get("adx") is not None]
    tpct=sum(1 for a in adx_v if a>ADX_TH)/len(adx_v)*100 if adx_v else 0
    
    r=run(sub)
    days=(sub[-1]["dt"]-sub[0]["dt"]).days
    
    print(f"\n{'─'*110}")
    print(f"📅 {pd}天 ({sub[0]['dt'].strftime('%m-%d')}~{sub[-1]['dt'].strftime('%m-%d')}, {len(sub)}根, 趋势{tpct:.0f}%)")
    print(f"   {r['n']}笔 | 胜率{r['wr']:.0f}% | 净{r['tn']:+.2f}% | ${r['usd']:+.2f} | 夏普{r['sh']:.2f} | RR{r['rr']:.2f}")
    
    if r["trades"]:
        longs=[t for t in r["trades"] if t["dir"]=="long"]
        shorts=[t for t in r["trades"] if t["dir"]=="short"]
        if longs:
            lw=sum(1 for t in longs if t["net"]>0)
            print(f"   多: {len(longs)}笔 胜{lw}/{len(longs)}={lw/len(longs)*100:.0f}% 盈亏{sum(t['net'] for t in longs):+.2f}%")
        if shorts:
            sw=sum(1 for t in shorts if t["net"]>0)
            print(f"   空: {len(shorts)}笔 胜{sw}/{len(shorts)}={sw/len(shorts)*100:.0f}% 盈亏{sum(t['net'] for t in shorts):+.2f}%")
        
        # 前5笔
        print(f"   最近5笔:")
        for t in sorted(r["trades"],key=lambda x:x["in_dt"])[-5:]:
            d="多🔴" if t["dir"]=="long" else "空🟢"
            print(f"     {d} {t['in_dt'].strftime('%m-%d %H:%M')}→{t['out_dt'].strftime('%m-%d %H:%M')} 毛{t['gp']:+.2f}% 净{t['net']:+.2f}% {t['reason']}")

# 汇总
print(f"\n{'='*110}")
print(f"📊 四周期汇总对比")
print(f"{'='*110}")
print(f"{'周期':<8} {'笔':>4} {'胜率':>7} {'净%':>9} {'$':>7} {'夏普':>6} {'RR':>5}")
print(f"{'─'*48}")
for pd in PERIODS:
    cutoff=now-timedelta(days=pd); ct=int(cutoff.timestamp()*1000)
    sub=[b for b in bars if b["ts"]>=ct]
    if len(sub)<100: continue
    r=run(sub)
    print(f"{pd:>4}天 {r['n']:>4} {r['w']}/{r['n']}={r['wr']:.0f}% {r['tn']:>+9.2f} {r['usd']:>+7.2f} {r['sh']:>6.2f} {r['rr']:>5.2f}")

# vs 前三个策略
print(f"\n📊 最终对比:")
print(f"{'策略':<28} {'15天':>8} {'30天':>8} {'60天':>8} {'90天':>8}")
print(f"{'─'*65}")
print(f"{'MA交叉(原)':<28} {'-7.93%':>8} {'-36.22%':>8} {'-59.85%':>8} {'-56.52%':>8}")
print(f"{'BB+RSI':<28} {'-2.23%':>8} {'+3.72%':>8} {'-9.79%':>8} {'-42.75%':>8}")
print(f"{'ADX自适应':<28} {'-7.14%':>8} {'-30.13%':>8} {'-47.51%':>8} {'-86.66%':>8}")
print(f"{'MA+ADX★(新)':<28} ",end="")
for pd in PERIODS:
    cutoff=now-timedelta(days=pd); ct=int(cutoff.timestamp()*1000)
    sub=[b for b in bars if b["ts"]>=ct]
    r=run(sub) if len(sub)>=100 else {"tn":0}
    print(f"{r['tn']:>+8.2f}%",end="")
print()
print(f"{'='*65}")
