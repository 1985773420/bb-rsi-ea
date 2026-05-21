#!/usr/bin/env python3
"""
50轮终极迭代: 系统性探索BB+RSI全参数空间
Batch 1: BB周期/标准差/RSI阈值变体
Batch 2: 离场策略 (中轨止盈/移动止损/时间优化)
Batch 3: 多时间框架+成交量+波动率精细化
Batch 4: 组合策略 + 自适应参数
Batch 5: 极端参数 + 最优微调
"""
import json, math, subprocess, time
from datetime import datetime, timezone, timedelta

# ===== 数据 =====
with open("/tmp/btc_15m_gate.json") as f: raw = json.load(f)
bars = []
for r in raw:
    bars.append({"ts": int(r[0]), "o": float(r[1]), "h": float(r[2]),
                 "l": float(r[3]), "c": float(r[4]),
                 "dt": datetime.fromtimestamp(int(r[0])/1000, tz=timezone.utc)})
bars.sort(key=lambda x: x["ts"]); n = len(bars)
closes=[b["c"] for b in bars]; highs=[b["h"] for b in bars]; lows=[b["l"] for b in bars]

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

# ===== 全量指标预计算 =====
def calc_all_bb(cl, periods=[10,14,20,30,50], stds=[1.5,2,2.5,3]):
    result={}
    for p in periods:
        for s in stds:
            bu,bl,bm=[],[],[]
            for i in range(len(cl)):
                if i>=p-1:
                    w=cl[i-p+1:i+1]; m=sum(w)/p
                    ss=math.sqrt(sum((x-m)**2 for x in w)/p)
                    bu.append(m+s*ss); bl.append(m-s*ss); bm.append(m)
                else: bu.append(None); bl.append(None); bm.append(None)
            result[f"bb{p}_{s}"]={"u":bu,"l":bl,"m":bm}
    return result

def calc_all_rsi(cl, periods=[7,10,14,21]):
    result={}
    for p in periods:
        r=[]; g=[]; l=[]
        for i in range(len(cl)):
            if i==0: g.append(0); l.append(0)
            else: ch=cl[i]-cl[i-1]; g.append(max(ch,0)); l.append(max(-ch,0))
            if i>=p:
                ag=sum(g[i-p+1:i+1])/p; al=sum(l[i-p+1:i+1])/p
                r.append(100-100/(1+ag/al) if al>0 else 100)
            else: r.append(None)
        result[f"rsi{p}"]=r
    return result

def calc_adx(n, highs, lows, closes):
    tr,pd,nd=[],[],[]
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
    at=ws(tr,14); pm=ws(pd,14); nm=ws(nd,14)
    adx_raw=[]
    for i in range(n):
        if at[i] is None or at[i]==0: adx_raw.append(None)
        else:
            pdi=pm[i]/at[i]*100; ndi=nm[i]/at[i]*100
            adx_raw.append(abs(pdi-ndi)/(pdi+ndi)*100 if pdi+ndi>0 else 0)
    sm=[]
    for i in range(n):
        if i<13: sm.append(adx_raw[i])
        elif None in adx_raw[i-13:i+1]: sm.append(None)
        else: sm.append(sum(adx_raw[i-13:i+1])/14)
    return sm

# ATR
tr_v=[max(highs[i]-lows[i],abs(highs[i]-closes[i-1]),abs(lows[i]-closes[i-1])) if i>0 else highs[i]-lows[i] for i in range(n)]
atr_pct=[sum(tr_v[max(0,i-13):i+1])/min(i+1,14)/closes[i]*100 for i in range(n)]
avg_atr=sum(v for v in atr_pct[100:] if v)/sum(1 for v in atr_pct[100:] if v)

# MA50
ma50=[sum(closes[i-49:i+1])/50 if i>=49 else None for i in range(n)]

# 成交量
vols=[float(b.get("v",0) or 0) for b in bars]
vol_sma20=[]
for i in range(n):
    if i>=19: vol_sma20.append(sum(vols[i-19:i+1])/20)
    else: vol_sma20.append(None)

print(f"预计算指标... avg_atr={avg_atr:.3f}%")
bb_alls=calc_all_bb(closes)
rsi_alls=calc_all_rsi(closes)
adx_sm=calc_adx(n,highs,lows,closes)

print(f"BB变体: {list(bb_alls.keys())}")
print(f"RSI变体: {list(rsi_alls.keys())}")

for i,bar in enumerate(bars):
    bar["idx"]=i
    for k,v in bb_alls.items():
        bar[f"{k}_u"]=v["u"][i]; bar[f"{k}_l"]=v["l"][i]; bar[f"{k}_m"]=v["m"][i]
    for k,v in rsi_alls.items():
        bar[k]=v[i]
    bar["adx"]=adx_sm[i]; bar["atr"]=atr_pct[i]
    bar["ma50"]=ma50[i]; bar["vol_ratio"]=vols[i]/vol_sma20[i] if vol_sma20[i] and vol_sma20[i]>0 else None

FEE=0.07; LEV=5; PERIODS=[15,30,60,90]; VALID=100
now=datetime.now(timezone.utc)

# ===== 回测引擎 =====
def run_bt(subset, entry_fn, exit_mode, tp, sl, mb):
    """exit_mode: 'fixed'|'mid'|'trail'|'mid_or_tp'"""
    trades=[]; pos=None
    for gi,bar in enumerate(subset):
        if pos is not None:
            c=bar["c"]; ep=pos["price"]; ei=pos["idx"]; held=gi-ei
            gp=(c-ep)/ep*100 if pos["type"]=="long" else (ep-c)/ep*100
            exit=False; reason=""
            
            if exit_mode=='fixed':
                if gp>=tp: exit=True; reason="tp"
                elif gp<=-sl: exit=True; reason="sl"
                elif held>=mb: exit=True; reason="to"
            elif exit_mode=='mid':
                bm=bar.get(pos.get("bb_key","bb20_2")+"_m")
                if pos["type"]=="long" and bm and c>=bm: exit=True; reason="mid"
                elif pos["type"]=="short" and bm and c<=bm: exit=True; reason="mid"
                elif gp<=-sl: exit=True; reason="sl"
                elif held>=mb: exit=True; reason="to"
            elif exit_mode=='trail':
                if gp>0: pos["best"]=max(pos.get("best",0),gp)
                trail_sl=pos.get("best",0)-sl
                if gp<trail_sl: exit=True; reason="trail"
                elif gp<=-sl: exit=True; reason="sl"
                elif held>=mb: exit=True; reason="to"
            elif exit_mode=='mid_or_tp':
                bm=bar.get(pos.get("bb_key","bb20_2")+"_m")
                if gp>=tp: exit=True; reason="tp"
                elif pos["type"]=="long" and bm and c>=bm: exit=True; reason="mid"
                elif pos["type"]=="short" and bm and c<=bm: exit=True; reason="mid"
                elif gp<=-sl: exit=True; reason="sl"
                elif held>=mb: exit=True; reason="to"
            
            if exit:
                net=(gp-FEE)*LEV
                trades.append({"dir":pos["type"],"gp":round(gp,4),"net":round(net,4),
                              "held":held,"reason":reason})
                pos=None
            elif exit_mode=='trail' and gp>0:
                pos["best"]=max(pos.get("best",0),gp)
            continue
        
        sig=entry_fn(bar)
        if sig:
            pos={"type":sig["dir"],"idx":gi,"price":bar["c"],"best":0,"bb_key":sig.get("bb_key","bb20_2")}
    
    if pos:
        c=subset[-1]["c"]; ep=pos["price"]
        gp=(c-ep)/ep*100 if pos["type"]=="long" else (ep-c)/ep*100
        net=(gp-FEE)*LEV
        trades.append({"dir":pos["type"],"gp":round(gp,4),"net":round(net,4),
                      "held":len(subset)-1-pos["idx"],"reason":"end"})
    
    if len(trades)<3: return None
    w=sum(1 for t in trades if t["net"]>0); nn=len(trades)
    tn=sum(t["net"] for t in trades); wr=w/nn*100 if nn else 0
    wt=[t["net"] for t in trades if t["net"]>0]; lt=[t["net"] for t in trades if t["net"]<=0]
    rr=(sum(wt)/len(wt))/(abs(sum(lt)/len(lt))) if wt and lt else 0
    if nn>1:
        pn=[t["net"] for t in trades]; a=sum(pn)/nn
        s=math.sqrt(sum((x-a)**2 for x in pn)/nn); sh=a/s*math.sqrt(nn) if s>0 else 0
    else: sh=0
    return {"n":nn,"w":w,"wr":wr,"tn":tn,"usd":tn/100*37.54,"rr":rr,"sh":sh,"trades":trades}

def score_it(entry_fn,exit_mode,tp,sl,mb):
    ss=0; cnt=0
    for pd in PERIODS:
        ct=int((now-timedelta(days=pd)).timestamp()*1000)
        sub=[b for b in bars[VALID:] if b["ts"]>=ct]
        if len(sub)<100: continue
        r=run_bt(sub,entry_fn,exit_mode,tp,sl,mb)
        if r is None or r["n"]<3: continue
        ss+=r["tn"]*0.5+r["sh"]*8*0.3+r["wr"]*0.2; cnt+=1
    return ss/max(cnt,1) if cnt else -999

# ===== 工厂函数 =====
def make_bb_entry(bb_key, rsi_key, rsi_short_th=65, rsi_long_th=35, 
                  vol_filter=None, adx_max=None, ma_dist_min=None, mom_filter=False):
    """通用BB+RSI入场工厂"""
    def e(bar):
        c=bar["c"]; m7=bar.get("ma730")
        bu=bar.get(f"{bb_key}_u"); bl=bar.get(f"{bb_key}_l")
        r=bar.get(rsi_key); at=bar.get("atr"); a=bar.get("adx")
        if None in (m7,bu,bl,r,at): return None
        
        # 波动率过滤
        if vol_filter and at<avg_atr*vol_filter: return None
        # ADX过滤
        if adx_max and a and a>adx_max: return None
        # MA距离过滤
        if ma_dist_min and abs(c-m7)/m7<ma_dist_min: return None
        # 动量过滤
        if mom_filter:
            idx=bar["idx"]
            if idx>=3:
                s_up=closes[idx]>closes[idx-1]>closes[idx-2]
                s_dn=closes[idx]<closes[idx-1]<closes[idx-2]
                if not (s_up or s_dn): return None
        
        if c<m7 and c>bu and r>rsi_short_th: return {"dir":"short","bb_key":bb_key}
        if c>m7 and c<bl and r<rsi_long_th: return {"dir":"long","bb_key":bb_key}
        return None
    return e

# ===== 迭代 =====
all_results=[]
iter_num=34

def test(name,entry_fn,exit_mode,tp,sl,mb,extra=""):
    global iter_num
    sc=score_it(entry_fn,exit_mode,tp,sl,mb)
    res={}
    for pd in PERIODS:
        ct=int((now-timedelta(days=pd)).timestamp()*1000)
        sub=[b for b in bars[VALID:] if b["ts"]>=ct]
        r=run_bt(sub,entry_fn,exit_mode,tp,sl,mb) if len(sub)>=100 else None
        res[pd]=r
    all_results.append({"num":iter_num,"name":name,"tp":tp,"sl":sl,"mb":mb,
                       "exit":exit_mode,"score":sc,"res":res,"extra":extra})
    # 简洁输出
    vs=[f"{res[pd]['tn']:+.1f}%" if res.get(pd) and res[pd]["n"]>=3 else "-" for pd in PERIODS]
    print(f"I{iter_num:>3} {name:<45} s={sc:>+6.1f} {vs[0]:>7} {vs[1]:>7} {vs[2]:>7} {vs[3]:>7}")
    iter_num+=1
    return sc

# ==========================================
print(f"\n{'='*110}")
print(f"50轮终极迭代 (Iter 34-83)")
print(f"{'='*110}")
print(f"{'Iter':<5} {'策略':<45} {'评分':>7} {'15d':>7} {'30d':>7} {'60d':>7} {'90d':>7}")
print(f"{'─'*85}")

# --- Batch 1: BB参数 + RSI阈值 (Iter 34-50) ---
print("\n--- Batch 1: BB周期/标准差/RSI阈值 ---")
for bb in ["bb20_2","bb14_2","bb30_2","bb20_1.5","bb20_2.5","bb20_3","bb10_2","bb50_2"]:
    for rsi_k in ["rsi14","rsi10","rsi7","rsi21"]:
        for rsi_h,rsi_l,lbl in [(65,35,"65/35"),(70,30,"70/30"),(75,25,"75/25"),(60,40,"60/40")]:
            fn=make_bb_entry(bb,rsi_k,rsi_h,rsi_l,vol_filter=0.8)
            test(f"{bb} {rsi_k} {lbl} HV=0.8",fn,'fixed',0.8,0.4,24)

# --- Batch 2: 离场策略 (Iter 51-60) ---
print("\n--- Batch 2: 离场策略 ---")
for exit_m,tp,sl,mb,lbl in [('mid',0.8,0.4,24,"中轨止盈"),
                             ('trail',0.8,0.35,24,"移动止损"),
                             ('mid_or_tp',0.8,0.4,24,"中轨或TP"),
                             ('mid',0.6,0.35,20,"中轨 TP0.6"),
                             ('trail',1.0,0.4,24,"移动止损 TP1.0"),
                             ('mid_or_tp',1.0,0.5,20,"中轨或TP 宽")]:
    fn=make_bb_entry("bb20_2","rsi14",65,35,vol_filter=0.8)
    test(f"BB20 HV=0.8 {lbl}",fn,exit_m,tp,sl,mb)

# --- Batch 3: 波动率阈值 + ADX + MA距离 (Iter 61-72) ---
print("\n--- Batch 3: 精细化过滤 ---")
for vf,adx_m,md,lbl in [(0.6,None,None,"HV0.6"),
                         (0.9,None,None,"HV0.9"),
                         (1.0,None,None,"HV1.0(>均值)"),
                         (0.7,25,None,"HV0.7 ADX<25"),
                         (0.8,20,None,"HV0.8 ADX<20"),
                         (0.7,None,0.02,"HV0.7 距MA>2%"),
                         (0.8,None,0.03,"HV0.8 距MA>3%"),
                         (0.7,20,0.02,"HV0.7 ADX<20 距MA2%"),
                         (0.8,15,None,"HV0.8 ADX<15"),
                         (0.5,None,None,"HV0.5(极低)"),
                         (1.2,None,None,"HV1.2(极高)")]:
    fn=make_bb_entry("bb20_2","rsi14",65,35,vol_filter=vf,adx_max=adx_m,ma_dist_min=md,mom_filter=False)
    test(f"BB20 {lbl}",fn,'fixed',0.8,0.4,24)

# --- Batch 4: 成交量 + MA50 + 组合信号 (Iter 73-80) ---
print("\n--- Batch 4: 成交量+MA50+多信号 ---")
# 高量入场
def make_highvol_entry():
    def e(bar):
        c=bar["c"]; m7=bar.get("ma730")
        bu=bar.get("bb20_2_u"); bl=bar.get("bb20_2_l"); r=bar.get("rsi14")
        at=bar.get("atr"); vr=bar.get("vol_ratio")
        if None in (m7,bu,bl,r,at,vr): return None
        if at<avg_atr*0.8 or vr<1.3: return None  # 高波动+放量
        if c<m7 and c>bu and r>65: return {"dir":"short","bb_key":"bb20_2"}
        if c>m7 and c<bl and r<35: return {"dir":"long","bb_key":"bb20_2"}
        return None
    return e
test("BB20 HV0.8 放量>1.3x",make_highvol_entry(),'fixed',0.8,0.4,24)

# MA50方向确认
def make_ma50_confirm():
    def e(bar):
        c=bar["c"]; m7=bar.get("ma730"); m50=bar.get("ma50")
        bu=bar.get("bb20_2_u"); bl=bar.get("bb20_2_l"); r=bar.get("rsi14"); at=bar.get("atr")
        if None in (m7,bu,bl,r,at,m50): return None
        if at<avg_atr*0.8: return None
        if c<m7 and c>bu and r>65 and c<m50: return {"dir":"short","bb_key":"bb20_2"}
        if c>m7 and c<bl and r<35 and c>m50: return {"dir":"long","bb_key":"bb20_2"}
        return None
    return e
test("BB20 HV0.8 MA50确认",make_ma50_confirm(),'fixed',0.8,0.4,24)

# MA50趋势 + BB
def make_ma50_bb():
    def e(bar):
        c=bar["c"]; m7=bar.get("ma730"); m50=bar.get("ma50")
        bu=bar.get("bb20_2_u"); bl=bar.get("bb20_2_l"); r=bar.get("rsi14"); at=bar.get("atr")
        if None in (m7,bu,bl,r,at,m50): return None
        if at<avg_atr*0.8: return None
        if c<m50 and c<m7 and c>bu and r>65: return {"dir":"short","bb_key":"bb20_2"}
        if c>m50 and c>m7 and c<bl and r<35: return {"dir":"long","bb_key":"bb20_2"}
        return None
    return e
test("BB20 HV0.8 MA50+MA730双确认",make_ma50_bb(),'fixed',0.8,0.4,24)

# 极简：只BB+RSI，无任何过滤
for tp,sl,mb,lbl in [(0.6,0.3,16,"紧"),(0.8,0.4,20,"中"),(1.0,0.5,24,"宽"),(1.2,0.6,28,"超宽")]:
    fn=make_bb_entry("bb20_2","rsi14",65,35)
    test(f"BB20纯{lbl} TP{tp}",fn,'fixed',tp,sl,mb)

# 最优组合：BB20 HV0.8 + mid exit
for tp,sl,mb,lbl in [(0.6,0.3,20,"窄"),(0.8,0.4,20,"中"),(1.0,0.5,24,"宽")]:
    fn=make_bb_entry("bb20_2","rsi14",65,35,vol_filter=0.8)
    test(f"BB20 HV0.8 中轨止盈{lbl}",fn,'mid_or_tp',tp,sl,mb)

# --- Batch 5: 终极组合 (Iter 81-83) ---
print("\n--- Batch 5: 终极微调 ---")
# 最优BB参数 + 最优过滤 + 最优离场
for bb,rk,rh,rl,vf,adxm,md in [("bb20_2","rsi14",65,35,0.8,None,None),
                                 ("bb14_2","rsi10",65,35,0.8,None,None),
                                 ("bb20_2","rsi14",70,30,0.7,20,None),
                                 ("bb30_2","rsi14",65,35,0.8,None,0.02)]:
    fn=make_bb_entry(bb,rk,rh,rl,vol_filter=vf,adx_max=adxm,ma_dist_min=md)
    lbl=f"{bb} {rk}{rh}/{rl} HV={vf}"
    if adxm: lbl+=f" ADX<{adxm}"
    if md: lbl+=f" dist>{md*100:.0f}%"
    for exit_m,tp,sl,mb,el in [('fixed',0.8,0.4,24,"fixed"),('mid_or_tp',0.8,0.4,24,"mid")]:
        test(f"{lbl} {el}",fn,exit_m,tp,sl,mb)

# ===== 最终排名 =====
print(f"\n{'='*110}")
print(f"🏆 50轮终极排名 Top 25")
print(f"{'='*110}")
all_results.sort(key=lambda x:-x["score"])
print(f"{'排名':<5} {'Iter':<5} {'策略':<50} {'评分':>7} {'15d':>7} {'30d':>7} {'60d':>7} {'90d':>7}")
print(f"{'─'*95}")

for i,r in enumerate(all_results[:25]):
    vs=[f"{r['res'][pd]['tn']:+.1f}%" if r['res'].get(pd) and r['res'][pd]['n']>=3 else "  -" for pd in PERIODS]
    m="★" if i==0 else " "
    print(f"{m}{i+1:<4} {r['num']:<5} {r['name']:<50} {r['score']:>+7.1f} {vs[0]:>7} {vs[1]:>7} {vs[2]:>7} {vs[3]:>7}")

best=all_results[0]
print(f"\n{'='*110}")
print(f"🌟 50轮最优: Iter {best['num']} — {best['name']}")
print(f"   TP{best['tp']}/SL{best['sl']}/{best['mb']}b | 离场:{best['exit']} | 评分:{best['score']:+.1f}")
print(f"   15d:{best['res'].get(15,{}).get('tn','-'):+.1f}% | 30d:{best['res'].get(30,{}).get('tn','-'):+.1f}% | 60d:{best['res'].get(60,{}).get('tn','-'):+.1f}% | 90d:{best['res'].get(90,{}).get('tn','-'):+.1f}%")
if best['res'].get(15):
    print(f"   15d: {best['res'][15]['n']}笔 胜{best['res'][15]['wr']:.0f}%")
if best['res'].get(30):
    print(f"   30d: {best['res'][30]['n']}笔 胜{best['res'][30]['wr']:.0f}%")
print(f"{'='*110}")
