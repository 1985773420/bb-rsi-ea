#!/usr/bin/env python3
"""15分钟策略深度优化: 防追高 + 参数搜索"""
import requests, math, time
from datetime import datetime

URL = "https://www.okx.com/api/v5/market/history-candles"
PROXY = "http://127.0.0.1:2080"
FEE = 0.0007

print("拉取15m数据...")
bars=[]
after=int(time.time()*1000)
while len(bars)<10000:
    r=requests.get(URL,params={"instId":"BTC-USDT","bar":"15m","limit":300,"after":str(after)},
                   proxies={"http":PROXY,"https":PROXY},timeout=30)
    data=r.json().get("data",[])
    if not data:break
    bars=[{"ts":int(row[0]),"c":float(row[4]),"h":float(row[2]),"l":float(row[3])} for row in data]+bars
    after=int(data[-1][0]);time.sleep(0.05)
bars.sort(key=lambda x:x["ts"])
print(f"15m: {len(bars)}根 | {datetime.fromtimestamp(bars[0]['ts']/1000).strftime('%Y-%m-%d')}~{datetime.fromtimestamp(bars[-1]['ts']/1000).strftime('%Y-%m-%d')}")

def calc(bars, bb_p, bb_s, rsi_p):
    cl=[b["c"]for b in bars];hi=[b["h"]for b in bars];lo=[b["l"]for b in bars];n=len(cl)
    bb_u,bb_l=[None]*n,[None]*n
    for i in range(bb_p-1,n):
        w=cl[i-bb_p+1:i+1];sma=sum(w)/bb_p;std=(sum((x-sma)**2 for x in w)/bb_p)**0.5
        bb_u[i]=sma+bb_s*std;bb_l[i]=sma-bb_s*std
    rs=[None]*n
    for i in range(rsi_p,n):
        g=sum(max(cl[j]-cl[j-1],0)for j in range(i-rsi_p+1,i+1))/rsi_p
        l=sum(max(cl[j-1]-cl[j],0)for j in range(i-rsi_p+1,i+1))/rsi_p
        rs[i]=100-100/(1+g/l)if l>0 else 100
    atr=[None]*n
    for i in range(14,n):
        tr=[max(hi[j]-lo[j],abs(hi[j]-cl[j-1]),abs(lo[j]-cl[j-1]))for j in range(i-13,i+1)]
        atr[i]=(sum(tr)/14)/cl[i]*100
    v=[v for v in atr if v is not None];am=sum(v)/len(v)if v else 0.1
    return bb_u,bb_l,rs,atr,am

def bt(bars, bb_p, bb_s, rsi_p, rsi_h, rsi_l, atr_f, tp, sl, max_b, anti_chase=0):
    """
    anti_chase: 防追高机制
    0=关, N=价格在近N根内涨超X%则不追
    """
    bb_u,bb_l,rs,atr,am=calc(bars,bb_p,bb_s,rsi_p)
    trades=[];in_pos=None;ep=0;eb=0;eq=[1.0]
    mi=max(bb_p,rsi_p,14)+1;n=len(bars)
    
    for i in range(mi,n):
        c=bars[i]["c"]
        if in_pos:
            h=i-eb;pnl=(c-ep)/ep if in_pos=="long" else (ep-c)/ep
            if pnl>=tp:trades.append({"p":pnl-FEE,"r":"TP","ts":bars[i]["ts"]});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            if pnl<=-sl:trades.append({"p":pnl-FEE,"r":"SL","ts":bars[i]["ts"]});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            if h>=max_b:trades.append({"p":pnl-FEE,"r":"TO","ts":bars[i]["ts"]});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            continue
        
        sig=None;sig_bar=None
        for j in range(i-1,max(i-4,mi-1),-1):
            if bb_u[j] is None or rs[j] is None or atr[j] is None:continue
            if atr[j]<am*atr_f:continue
            cj=bars[j]["c"]
            
            # 防追高: 长信号检查近N根已涨多少
            if rs[j] > rsi_h and cj > bb_u[j]:
                chase_ok = True
                if anti_chase > 0:
                    # 查近anti_chase根最高价距当前
                    peak = max(bars[k]["h"] for k in range(j, min(j+anti_chase, n)))
                    if cj >= peak * 0.995:  # 价格接近近期高点，不追
                        chase_ok = False
                if chase_ok:
                    sig="short";sig_bar=j;break
            
            elif rs[j] < rsi_l and cj < bb_l[j]:
                chase_ok = True
                if anti_chase > 0:
                    trough = min(bars[k]["l"] for k in range(j, min(j+anti_chase, n)))
                    if cj <= trough * 1.005:
                        chase_ok = False
                if chase_ok:
                    sig="long";sig_bar=j;break
        
        if not sig:continue
        ep=bars[sig_bar]["c"];in_pos=sig;eb=i
    
    if in_pos:
        c=bars[-1]["c"];pnl=(c-ep)/ep if in_pos=="long" else (ep-c)/ep
        trades.append({"p":pnl-FEE,"r":"OPEN","ts":bars[-1]["ts"]})
    return trades,eq

# ===== 大网格 =====
COMBS = [
    # 基准
    (20,2,10, 65,35, 0.6, 0.005,0.003, 24, 0),
    # 防追高
    (20,2,10, 65,35, 0.6, 0.005,0.003, 24, 3),
    (20,2,10, 65,35, 0.6, 0.005,0.003, 24, 5),
    # 收紧BB
    (15,2,10, 65,35, 0.6, 0.005,0.003, 24, 0),
    (15,2,10, 65,35, 0.6, 0.005,0.003, 24, 3),
    # RSI敏感化
    (20,2,7, 70,30, 0.6, 0.005,0.003, 24, 0),
    (20,2,7, 70,30, 0.6, 0.005,0.003, 24, 3),
    (15,2,7, 70,30, 0.6, 0.005,0.003, 24, 0),
    (15,2,7, 70,30, 0.6, 0.005,0.003, 24, 3),
    # TP/SL优化
    (20,2,10, 65,35, 0.6, 0.006,0.004, 24, 0),
    (20,2,10, 65,35, 0.6, 0.006,0.004, 24, 3),
    (20,2,7, 70,30, 0.6, 0.006,0.004, 24, 0),
    (20,2,7, 70,30, 0.6, 0.006,0.004, 24, 3),
    # 放宽ATR
    (20,2,10, 65,35, 0.4, 0.005,0.003, 24, 0),
    (20,2,10, 65,35, 0.4, 0.005,0.003, 24, 3),
    (15,2,7, 70,30, 0.4, 0.005,0.003, 24, 0),
    (15,2,7, 70,30, 0.4, 0.005,0.003, 24, 3),
    # 短持仓
    (20,2,10, 65,35, 0.6, 0.005,0.003, 16, 0),
    (20,2,10, 65,35, 0.6, 0.005,0.003, 16, 3),
    # 极端RSI + 防追高
    (20,2,10, 70,30, 0.5, 0.005,0.003, 24, 3),
    (15,2,7, 75,25, 0.5, 0.005,0.003, 24, 3),
    # 组合
    (20,2,7, 70,30, 0.5, 0.004,0.003, 20, 3),
    (15,2,7, 70,30, 0.5, 0.004,0.003, 20, 3),
    (20,2,10, 70,30, 0.5, 0.004,0.003, 20, 3),
]

print(f"\n网格搜索 {len(COMBS)} 组...")
results=[]
for bb_p,bb_s,rsi_p,rsi_h,rsi_l,atr_f,tp,sl,max_b,anti in COMBS:
    # 用最近60天快速评估
    recent=bars[-60*96:]
    trades,eq=bt(recent,bb_p,bb_s,rsi_p,rsi_h,rsi_l,atr_f,tp,sl,max_b,anti)
    if not trades:continue
    wins=[t for t in trades if t["p"]>0];losses=[t for t in trades if t["p"]<=0]
    ec=1.0
    for t in trades:ec*=(1+t["p"])
    comp=(ec-1)*100;wr=len(wins)/len(trades)*100
    avg_w=sum(t["p"]for t in wins)/len(wins)*100 if wins else 0
    avg_l=sum(t["p"]for t in losses)/len(losses)*100 if losses else 0
    tp_n=sum(1 for t in trades if t["r"]=="TP");sl_n=sum(1 for t in trades if t["r"]=="SL")
    
    anti_label=f"防追{anti}" if anti>0 else "无防护"
    results.append({
        "label":f"{anti_label} BB({bb_p},{bb_s}) RSI{rsi_p}[{rsi_h}/{rsi_l}] x{atr_f} TP{tp*100}% SL{sl*100}% {max_b}b",
        "n":len(trades),"wr":wr,"comp":comp,"tp":tp_n,"sl":sl_n,
        "params":(bb_p,bb_s,rsi_p,rsi_h,rsi_l,atr_f,tp,sl,max_b,anti)
    })

results.sort(key=lambda x: x["comp"], reverse=True)

print(f"\n{'='*95}")
print(f"📊 前12名")
print(f"{'='*95}")
for i,r in enumerate(results[:12]):
    flag="🏆"if i==0 else"  "
    print(f"{flag} {i+1:>2}. {r['label']}")
    print(f"     {r['n']}笔 | 胜率{r['wr']:.1f}% | 复利{r['comp']:+.2f}% | TP{r['tp']} SL{r['sl']}")

# 前3跑完整180天
print(f"\n{'='*95}")
print(f"前3名 180天验证")
print(f"{'='*95}")
best_overall=("",-999,-999)
for i in range(min(3,len(results))):
    r=results[i]
    params=r["params"]
    for days in [30,60,90,180]:
        start=max(0,len(bars)-days*96)
        trades,eq=bt(bars[start:],*params)
        if not trades:continue
        wins=[t for t in trades if t["p"]>0]
        ec=1.0
        for t in trades:ec*=(1+t["p"])
        comp=(ec-1)*100
        
        dd_str=""
        if days==180:
            peak=1.0;max_dd=0
            for v in eq:
                if v>peak:peak=v
                dd=peak-v
                if dd>max_dd:max_dd=dd
            dd_str=f" | 回撤{max_dd*100:.1f}%"
            if comp>best_overall[2]:
                best_overall=(r["label"],comp,max_dd*100)
        
        print(f"  #{i+1} {days:>3}天: {len(trades):>4}笔 | 胜率{len(wins)/len(trades)*100:.1f}% | 复利{comp:+7.2f}%{dd_str}")
    print()

# 基准对比
print(f"\n{'='*95}")
print(f"📊 vs 基准")
print(f"{'='*95}")
t_base,eq_base=bt(bars,20,2,10,65,35,0.6,0.005,0.003,24,0)
w_base=[t for t in t_base if t["p"]>0]
ec_base=1.0
for t in t_base:ec_base*=(1+t["p"])
print(f"基准(15m原): {len(t_base)}笔 | 胜率{len(w_base)/len(t_base)*100:.1f}% | 复利{(ec_base-1)*100:+.2f}%")
print(f"最优: {best_overall[0]}")
print(f"      复利{best_overall[1]:+.2f}% | 回撤{best_overall[2]:.1f}%")
print(f"      提升: 复利{best_overall[1]-(ec_base-1)*100:+.2f}%")
