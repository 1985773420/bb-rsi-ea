#!/usr/bin/env python3
"""5分钟 180天完整回测 + 参数优化"""
import requests, math, time
from datetime import datetime

URL = "https://www.okx.com/api/v5/market/history-candles"
PROXY = "http://127.0.0.1:2080"
FEE = 0.0007

print("拉取5m 180天数据 (目标~51840根)...")
bars = []
after = int(time.time() * 1000)
page = 0
while len(bars) < 50000 and page < 200:
    try:
        r = requests.get(URL, params={"instId":"BTC-USDT","bar":"5m","limit":300,"after":str(after)},
                         proxies={"http":PROXY,"https":PROXY}, timeout=30)
        data = r.json().get("data", [])
        if not data: break
        bars = [{"ts":int(row[0]),"c":float(row[4]),"h":float(row[2]),"l":float(row[3])} for row in data] + bars
        after = int(data[-1][0]); page += 1
        if page % 20 == 0:
            print(f"  第{page}页 {len(bars)}根, 最早{datetime.fromtimestamp(bars[0]['ts']/1000).strftime('%Y-%m-%d')}")
        time.sleep(0.05)
    except: break
bars.sort(key=lambda x:x["ts"])
print(f"\n✅ {len(bars)}根 | {datetime.fromtimestamp(bars[0]['ts']/1000).strftime('%Y-%m-%d %H:%M')} ~ {datetime.fromtimestamp(bars[-1]['ts']/1000).strftime('%Y-%m-%d %H:%M')}")

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
            if pnl>=tp:trades.append({"p":pnl-FEE,"r":"TP","ts":bars[i]["ts"]});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            if pnl<=-sl:trades.append({"p":pnl-FEE,"r":"SL","ts":bars[i]["ts"]});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
            if h>=max_b:trades.append({"p":pnl-FEE,"r":"TO","ts":bars[i]["ts"]});eq.append(eq[-1]*(1+pnl-FEE));in_pos=None;continue
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
        trades.append({"p":pnl-FEE,"r":"OPEN","ts":bars[-1]["ts"]})
    return trades,eq

# ===== 大网格搜索 =====
COMBS = [
    # BB周期, BB标准差, RSI周期, RSI高/低, ATR, TP, SL, 最大持仓
    # 基础变体
    (20,2,10, 65,35, 0.4, 0.005,0.003, 24*3),
    (20,2,10, 65,35, 0.5, 0.005,0.003, 24*3),
    (20,2,7, 70,30, 0.4, 0.005,0.003, 24*3),
    (15,2,7, 70,30, 0.4, 0.005,0.003, 24*3),
    (15,1.5,7, 70,30, 0.4, 0.005,0.003, 24*3),
    (15,1.5,7, 65,35, 0.4, 0.005,0.003, 24*3),
    # TP/SL变体
    (20,2,10, 65,35, 0.4, 0.004,0.003, 24*3),
    (15,1.5,7, 70,30, 0.4, 0.004,0.003, 24*3),
    (15,1.5,7, 65,35, 0.4, 0.004,0.003, 24*3),
    (20,2,10, 65,35, 0.4, 0.006,0.004, 24*3),
    # RSI阈值
    (15,1.5,7, 75,25, 0.4, 0.005,0.003, 24*3),
    (20,2,7, 75,25, 0.4, 0.005,0.003, 24*3),
    # ATR
    (20,2,10, 65,35, 0.3, 0.005,0.003, 24*3),
    (15,1.5,7, 70,30, 0.3, 0.005,0.003, 24*3),
    # 持仓时间
    (20,2,10, 65,35, 0.4, 0.005,0.003, 24*2),
    (15,1.5,7, 70,30, 0.4, 0.005,0.003, 24*2),
]

print(f"\n网格搜索 {len(COMBS)} 组...")
results = []
for bb_p,bb_s,rsi_p,rsi_h,rsi_l,atr_f,tp,sl,max_b in COMBS:
    # 用最近30天数据快速评估
    recent = bars[-30*288:]
    trades,eq = bt(recent, bb_p,bb_s,rsi_p,rsi_h,rsi_l,atr_f,tp,sl,max_b)
    if not trades: continue
    wins=[t for t in trades if t["p"]>0]; losses=[t for t in trades if t["p"]<=0]
    ec=1.0
    for t in trades: ec*=(1+t["p"])
    comp=(ec-1)*100; wr=len(wins)/len(trades)*100
    avg_w=sum(t["p"]for t in wins)/len(wins)*100 if wins else 0
    avg_l=sum(t["p"]for t in losses)/len(losses)*100 if losses else 0
    
    results.append({
        "p": (bb_p,bb_s,rsi_p,rsi_h,rsi_l,atr_f,tp,sl,max_b),
        "label": f"BB({bb_p},{bb_s}) RSI{rsi_p}[{rsi_h}/{rsi_l}] x{atr_f} TP{tp*100}% SL{sl*100}% {max_b}b",
        "n":len(trades),"wr":wr,"comp":comp,"avg_w":avg_w,"avg_l":avg_l
    })

results.sort(key=lambda x: x["comp"], reverse=True)

print(f"\n{'='*95}")
print(f"📊 30天快速排名前8")
print(f"{'='*95}")
for i, r in enumerate(results[:8]):
    flag = "🏆" if i==0 else "  "
    print(f"{flag} {r['label']}")
    print(f"     {r['n']}笔 | 胜率{r['wr']:.1f}% | 复利{r['comp']:+.2f}% | 均赢{r['avg_w']:+.2f}% 均亏{r['avg_l']:+.2f}%")

# 取前3名跑完整180天
print(f"\n{'='*95}")
print(f"前3名跑完整180天")
print(f"{'='*95}")

for i in range(min(3, len(results))):
    r = results[i]
    p = r["p"]
    for days in [30, 60, 90, 180]:
        start = max(0, len(bars) - days*288)
        period_bars = bars[start:]
        trades, eq = bt(period_bars, *p)
        if not trades: continue
        wins = [t for t in trades if t["p"]>0]
        ec = 1.0
        for t in trades: ec *= (1+t["p"])
        comp = (ec-1)*100
        tp_n = sum(1 for t in trades if t["r"]=="TP")
        sl_n = sum(1 for t in trades if t["r"]=="SL")
        
        if days == 180:
            # 最大回撤
            peak=1.0; max_dd=0
            for v in eq:
                if v>peak: peak=v
                dd=peak-v
                if dd>max_dd: max_dd=dd
            dd_str = f" | 回撤{max_dd*100:.1f}%"
        else:
            dd_str = ""
        
        print(f"  #{i+1} {days:>3}天: {len(trades):>4}笔 | 胜率{len(wins)/len(trades)*100:.1f}% | 复利{comp:+7.2f}%{dd_str}")
    
    # 收益预估
    t180,eq180=bt(bars,*p)
    wins=sum(1 for t in t180 if t["p"]>0); losses=len(t180)-wins
    aw=sum(t["p"]for t in t180 if t["p"]>0)/wins if wins else 0
    al=sum(t["p"]for t in t180 if t["p"]<=0)/losses if losses else 0
    bal=37.54;lev=10;btc_=bars[-1]["c"];ct_val=btc_*0.01
    ct=max(0.01,round(bal*0.5/(ct_val/lev)*100)/100)
    profit=wins*ct*ct_val*aw-losses*ct*ct_val*abs(al)
    print(f"     💰 10x/50%: {ct:.2f}张 | {len(t180)}笔 | 净利${profit:+.2f} ({profit/bal*100:+.1f}%)")
    print()
