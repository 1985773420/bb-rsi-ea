#!/usr/bin/env python3
"""5分钟回测 + 参数优化"""
import requests, math, time
from datetime import datetime

URL = "https://www.okx.com/api/v5/market/history-candles"
PROXY = "http://127.0.0.1:2080"
FEE = 0.0007

print("拉取5m数据...")
bars = []
after = int(time.time() * 1000)
for _ in range(8):
    r = requests.get(URL, params={"instId":"BTC-USDT","bar":"5m","limit":300,"after":str(after)},
                     proxies={"http":PROXY,"https":PROXY}, timeout=30)
    data = r.json().get("data", [])
    if not data: break
    bars = [{"ts":int(row[0]),"c":float(row[4]),"h":float(row[2]),"l":float(row[3])} for row in data] + bars
    after = int(data[-1][0]); time.sleep(0.05)
bars.sort(key=lambda x:x["ts"])
print(f"5m: {len(bars)}根 | {datetime.fromtimestamp(bars[0]['ts']/1000).strftime('%m-%d %H:%M')}~{datetime.fromtimestamp(bars[-1]['ts']/1000).strftime('%m-%d %H:%M')}")

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

def bt(bars, bb_p, bb_s, rsi_p, rsi_h, rsi_l, atr_f, tp, sl, max_b):
    bb_u,bb_l,rs,atr,am=calc(bars,bb_p,bb_s,rsi_p)
    trades=[];in_pos=None;ep=0;eb=0;eq=[1.0]
    mi=max(bb_p,rsi_p,14)+1;n=len(bars)
    for i in range(mi,n):
        c=bars[i]["c"]
        if in_pos:
            h=i-eb;pnl=(c-ep)/ep if in_pos=="long" else (ep-c)/ep
            if pnl>=tp:trades.append({"p":pnl-FEE,"r":"TP"});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            if pnl<=-sl:trades.append({"p":pnl-FEE,"r":"SL"});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            if h>=max_b:trades.append({"p":pnl-FEE,"r":"TO"});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            continue
        sig=None;sig_bar=None
        for j in range(i-1,max(i-4,mi-1),-1):
            if bb_u[j] is None or rs[j] is None or atr[j] is None:continue
            if atr_f>0 and atr[j]<am*atr_f:continue
            cj=bars[j]["c"]
            if cj>bb_u[j] and rs[j]>rsi_h:sig="short";sig_bar=j;break
            elif cj<bb_l[j] and rs[j]<rsi_l:sig="long";sig_bar=j;break
        if not sig:continue
        ep=bars[sig_bar]["c"];in_pos=sig;eb=i
    if in_pos:
        c=bars[-1]["c"];pnl=(c-ep)/ep if in_pos=="long" else (ep-c)/ep
        trades.append({"p":pnl-FEE,"r":"OPEN"})
    return trades,eq

# 全网格: BB周期, BB标准差, RSI周期, RSI高低, ATR, TP, SL, 持仓限制
COMBS = [
    # 15m基准参数直接套5m
    (20,2,10, 65,35, 0.6, 0.005,0.003, 24*3),  # 5m: 24*3=72根=6h
    (20,2,10, 65,35, 0.4, 0.005,0.003, 24*3),
    # 收紧BB
    (15,1.5,10, 65,35, 0.4, 0.005,0.003, 24*3),
    (15,1.5,10, 70,30, 0.4, 0.005,0.003, 24*3),
    (12,1.5,10, 65,35, 0.4, 0.004,0.003, 24*3),
    # 敏感RSI
    (15,1.5,7, 70,30, 0.4, 0.005,0.003, 24*3),
    (20,2,7, 70,30, 0.4, 0.005,0.003, 24*3),
    # 更紧TP
    (15,1.5,10, 65,35, 0.4, 0.004,0.003, 24*3),
    (20,2,10, 65,35, 0.4, 0.004,0.003, 24*3),
    # 更宽TP
    (20,2,10, 60,40, 0.4, 0.008,0.004, 24*3),
    (20,2,10, 60,40, 0.4, 0.006,0.004, 24*3),
    # 混合
    (15,1.5,7, 65,35, 0.4, 0.004,0.003, 24*3),
    (12,1.5,7, 70,30, 0.4, 0.004,0.003, 24*3),
    # ATR宽松
    (15,1.5,10, 65,35, 0.3, 0.005,0.003, 24*3),
    (20,2,10, 60,40, 0.3, 0.006,0.004, 24*3),
]

print(f"\n网格搜索 {len(COMBS)} 组...")
results = []
for bb_p,bb_s,rsi_p,rsi_h,rsi_l,atr_f,tp,sl,max_b in COMBS:
    trades,eq = bt(bars, bb_p,bb_s,rsi_p,rsi_h,rsi_l,atr_f,tp,sl,max_b)
    if not trades: continue
    wins=[t for t in trades if t["p"]>0]; losses=[t for t in trades if t["p"]<=0]
    ec=1.0
    for t in trades: ec*=(1+t["p"])
    comp=(ec-1)*100; wr=len(wins)/len(trades)*100
    avg_w=sum(t["p"]for t in wins)/len(wins)*100 if wins else 0
    avg_l=sum(t["p"]for t in losses)/len(losses)*100 if losses else 0
    tp_n=sum(1 for t in trades if t["r"]=="TP"); sl_n=sum(1 for t in trades if t["r"]=="SL")
    to_n=len(trades)-tp_n-sl_n
    
    results.append({
        "label": f"BB({bb_p},{bb_s}) RSI{rsi_p}[{rsi_h}/{rsi_l}] x{atr_f} TP{tp*100}% SL{sl*100}% {max_b}b",
        "n":len(trades),"wr":wr,"comp":comp,"avg_w":avg_w,"avg_l":avg_l,"tp_n":tp_n,"sl_n":sl_n,"to_n":to_n
    })

results.sort(key=lambda x: x["comp"], reverse=True)

print(f"\n{'='*95}")
for i, r in enumerate(results[:10]):
    flag = "🏆" if i==0 else "  "
    print(f"{flag} {i+1}. {r['label']}")
    print(f"     {r['n']}笔 | 胜率{r['wr']:.1f}% | 复利{r['comp']:+.2f}% | TP{r['tp_n']} SL{r['sl_n']} TO{r['to_n']} | 均赢{r['avg_w']:+.2f}% 均亏{r['avg_l']:+.2f}%")

if results and results[0]["comp"] > 0:
    print(f"\n✅ 5分钟有正收益方案！最优复利 {results[0]['comp']:+.2f}%")
else:
    print(f"\n❌ 5分钟最优也只有 {results[0]['comp']:+.2f}%")
