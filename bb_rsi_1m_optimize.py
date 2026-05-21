#!/usr/bin/env python3
"""1分钟策略网格搜索最优参数"""
import requests, math, time, itertools
from datetime import datetime

URL = "https://www.okx.com/api/v5/market/history-candles"
PROXY = "http://127.0.0.1:2080"
FEE = 0.0007

print("拉取1m数据...")
bars_1m = []
after = int(time.time() * 1000)
for _ in range(15):
    r = requests.get(URL, params={"instId":"BTC-USDT","bar":"1m","limit":300,"after":str(after)},
                     proxies={"http":PROXY,"https":PROXY}, timeout=30)
    data = r.json().get("data", [])
    if not data: break
    bars_1m = [{"ts":int(row[0]),"c":float(row[4]),"h":float(row[2]),"l":float(row[3])} for row in data] + bars_1m
    after = int(data[-1][0]); time.sleep(0.05)
bars_1m.sort(key=lambda x:x["ts"])
print(f"1m: {len(bars_1m)}根 | {datetime.fromtimestamp(bars_1m[0]['ts']/1000).strftime('%m-%d %H:%M')}~{datetime.fromtimestamp(bars_1m[-1]['ts']/1000).strftime('%m-%d %H:%M')}")

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

def bt(bars, bb_p, bb_s, rsi_p, rsi_h, rsi_l, atr_f, tp, sl, max_bars):
    bb_u,bb_l,rs,atr,am=calc(bars,bb_p,bb_s,rsi_p)
    trades=[];in_pos=None;ep=0;eb=0;eq=[1.0]
    mi=max(bb_p,rsi_p,14)+1;n=len(bars)
    
    for i in range(mi,n):
        c=bars[i]["c"]
        if in_pos:
            h=i-eb;pnl=(c-ep)/ep if in_pos=="long" else (ep-c)/ep
            if pnl>=tp:trades.append({"p":pnl-FEE,"r":"TP"});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            if pnl<=-sl:trades.append({"p":pnl-FEE,"r":"SL"});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            if h>=max_bars:trades.append({"p":pnl-FEE,"r":"TO"});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
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

# 参数网格
COMBS = [
    # BB, RSI周期, RSI阈值, ATR, TP, SL, MAX_BARS
    # 基准
    (20,2,10, 65,35, 0.6, 0.005,0.003, 96),
    # 收紧BB
    (10,2,10, 70,30, 0.6, 0.005,0.003, 96),
    (10,1.5,10, 70,30, 0.6, 0.005,0.003, 96),
    (15,1.5,10, 70,30, 0.6, 0.005,0.003, 96),
    # 敏感RSI
    (10,1.5,7, 75,25, 0.6, 0.005,0.003, 96),
    (10,1.5,7, 80,20, 0.6, 0.005,0.003, 96),
    (20,2,7, 75,25, 0.6, 0.005,0.003, 96),
    # 更紧止盈
    (10,1.5,10, 70,30, 0.6, 0.003,0.002, 60),
    (10,1.5,7, 75,25, 0.6, 0.003,0.002, 60),
    (15,1.5,7, 75,25, 0.6, 0.003,0.002, 60),
    # 放宽ATR
    (10,1.5,10, 70,30, 0.3, 0.005,0.003, 96),
    (10,1.5,7, 75,25, 0.3, 0.005,0.003, 96),
    # 极端RSI
    (20,2,5, 80,20, 0.6, 0.005,0.003, 96),
    (10,1.5,5, 80,20, 0.3, 0.005,0.003, 60),
    # 微弱信号+紧TP
    (10,1.5,7, 75,25, 0.3, 0.002,0.0015, 30),
    (15,1.5,7, 80,20, 0.3, 0.002,0.0015, 30),
    # 短周期
    (5,1.5,5, 80,20, 0.3, 0.005,0.003, 60),
    (5,1.5,5, 75,25, 0.3, 0.003,0.002, 30),
]

print(f"\n测试 {len(COMBS)} 种组合...")
results = []
for i, (bb_p,bb_s,rsi_p,rsi_h,rsi_l,atr_f,tp,sl,max_b) in enumerate(COMBS):
    trades,eq = bt(bars_1m, bb_p,bb_s,rsi_p,rsi_h,rsi_l,atr_f,tp,sl,max_b)
    if not trades: continue
    wins=[t for t in trades if t["p"]>0]
    losses=[t for t in trades if t["p"]<=0]
    ec=1.0
    for t in trades: ec*=(1+t["p"])
    comp=(ec-1)*100
    wr=len(wins)/len(trades)*100
    avg_w=sum(t["p"]for t in wins)/len(wins)*100 if wins else 0
    avg_l=sum(t["p"]for t in losses)/len(losses)*100 if losses else 0
    
    # 综合评分: 复利为主, 胜率和交易量为辅
    score = comp + wr*0.1 + len(trades)*0.001
    
    tp_n=sum(1 for t in trades if t["r"]=="TP")
    sl_n=sum(1 for t in trades if t["r"]=="SL")
    
    results.append({
        "params": f"BB({bb_p},{bb_s}) RSI{rsi_p}[{rsi_h}/{rsi_l}] ATR{atr_f} TP{tp*100}% SL{sl*100}% {max_b}b",
        "n": len(trades), "wr": wr, "comp": comp, "score": score,
        "avg_w": avg_w, "avg_l": avg_l, "tp_n": tp_n, "sl_n": sl_n,
        "bb_p": bb_p, "bb_s": bb_s, "rsi_p": rsi_p, "rsi_h": rsi_h, "rsi_l": rsi_l,
        "atr_f": atr_f, "tp": tp, "sl": sl, "max_b": max_b
    })

results.sort(key=lambda x: x["score"], reverse=True)

print(f"\n{'='*95}")
print(f"📊 排名 (共{len(results)}组)")
print(f"{'='*95}")
for i, r in enumerate(results[:15]):
    flag = "🏆" if i==0 else "  "
    print(f"{flag} {i+1:>2}. {r['params']}")
    print(f"      {r['n']}笔 | 胜率{r['wr']:.1f}% | 复利{r['comp']:+.2f}% | TP{r['tp_n']} SL{r['sl_n']} | 均赢{r['avg_w']:+.2f}% 均亏{r['avg_l']:+.2f}%")

print(f"\n{'='*95}")
best = results[0]
print(f"🏆 最优: {best['params']}")
print(f"   {best['n']}笔 | 胜率{best['wr']:.1f}% | 复利{best['comp']:+.2f}%")
